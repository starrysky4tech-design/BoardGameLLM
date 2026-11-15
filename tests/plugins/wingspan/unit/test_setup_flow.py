"""初期選択(対局の開始)のテスト。実画面は 2 局目の初期選択(203_select、205_confirm)。

画面: 鳥 5 枚(ハシビロガモ、アメリカヤマセミ、アメリカワシミミズク、アメリカヨタカ、ヤブガラ)と餌 5 種から 5 つ。
アメリカヨタカは札の表に無い(読めない札として扱う)。
"""

import itertools
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import pytest

from bglm.core.models import Frame, InputAction, UiKind
from bglm.plugins.wingspan.logic.cards import default_table
from bglm.plugins.wingspan.logic.models import UNKNOWN_CARD, Food
from bglm.plugins.wingspan.logic.rules import WingspanRules
from bglm.plugins.wingspan.logic.state import KeepSetup, SetupTask
from bglm.plugins.wingspan.vision import layout
from bglm.plugins.wingspan.vision.dialogs import (
    SetupKind,
    classify_setup_title,
    read_setup,
)
from bglm.plugins.wingspan.vision.executor import WingspanExecutor
from bglm.plugins.wingspan.vision.ocr import JAPANESE_REC_MODEL, japanese_reader
from bglm.plugins.wingspan.vision.recognizer import WingspanRecognizer
from bglm.plugins.wingspan.vision.tracker import Tracker

TABLE = default_table()
RULES = WingspanRules(TABLE)
DATA = Path("datasets/raw/wingspan/feasibility")
needs_real = pytest.mark.skipif(
    not JAPANESE_REC_MODEL.exists() or not (DATA / "203_select.png").exists(),
    reason="日本語の認識モデルまたは実画面が無い(Git 管理外)",
)


def test_setup_titles_are_classified_from_measured_texts() -> None:
    assert (
        classify_setup_title("鳥カードと餌の中からキープしたいものを5 (0/5) 選んでください:")
        is SetupKind.KEEP
    )
    assert (
        classify_setup_title("キープする1 (0/1) ボーナスカードを選んでください。")
        is SetupKind.BONUS
    )
    assert classify_setup_title("ラウンド2/4 残り6手番 タップして手番を開始する") is SetupKind.NONE
    assert classify_setup_title("") is SetupKind.NONE


@needs_real
def test_real_setup_screens() -> None:
    reader = japanese_reader(scale=2)
    assert read_setup(cv2.imread(str(DATA / "203_select.png")), reader) is SetupKind.KEEP
    assert read_setup(cv2.imread(str(DATA / "205_confirm.png")), reader) is SetupKind.BONUS
    assert read_setup(cv2.imread(str(DATA / "289.png")), reader) is SetupKind.NONE


@needs_real
def test_recognizer_builds_the_setup_state_from_the_selection_screen() -> None:
    rec = WingspanRecognizer(me=0, table=TABLE, read_lines=japanese_reader(scale=2))
    result = rec.recognize(cv2.imread(str(DATA / "203_select.png")), None)
    assert result.ui.kind is UiKind.PLAYABLE and result.ui.screen == "setup:keep"
    state = result.state
    assert state is not None and isinstance(state.queue[0], SetupTask)
    assert state.players[0].hand == (
        "ハシビロガモ",
        "アメリカヤマセミ",
        "アメリカワシミミズク",
        UNKNOWN_CARD,  # アメリカヨタカは表に無い
        "ヤブガラ",
    )
    assert state.pending_setup == (0,) and state.players[0].cubes == 8
    # 追跡の状態が残っていれば、同じ画面でそれを返す(読み直さない)
    again = rec.recognize(cv2.imread(str(DATA / "203_select.png")), state)
    assert again.state is state


@needs_real
def test_setup_state_offers_keep_moves_and_the_strategy_picks_a_supported_one() -> None:
    rec = WingspanRecognizer(me=0, table=TABLE, read_lines=japanese_reader(scale=2))
    state = rec.recognize(cv2.imread(str(DATA / "203_select.png")), None).state
    assert state is not None
    legal = RULES.legal_moves(state)
    assert legal and all(isinstance(m, KeepSetup) for m in legal)
    assert all(len(m.birds) + len(m.foods) == 5 for m in legal)  # R p.2: 鳥の数 + 餌の数 = 5
    after = RULES.apply(state, legal[0])
    assert (
        after.pending_setup == ()
        and not after.queue
        and len(after.players[0].hand) == len(legal[0].birds)
    )


class FakeIo:
    def __init__(self) -> None:
        self.actions: list[InputAction] = []

    def capture(self) -> Frame:
        return Frame.from_image(np.zeros((1080, 2432, 3), dtype=np.uint8), datetime(2026, 11, 14))

    def perform(self, action: InputAction) -> None:
        self.actions.append(action)


class Scripted:
    def __init__(self, names: list[str]) -> None:
        self.names, self.calls = names, 0

    def screen_name(self, _image: object) -> str:
        name = self.names[min(self.calls, len(self.names) - 1)]
        self.calls += 1
        return name


def test_keep_setup_presses_the_chosen_cards_foods_and_the_left_bonus() -> None:
    from dataclasses import replace

    from bglm.plugins.wingspan.logic.goals import all_goal_tiles
    from bglm.plugins.wingspan.logic.models import PlayerBoard
    from bglm.plugins.wingspan.logic.state import WingspanState

    hand = ("ハシビロガモ", "アメリカヤマセミ", "アメリカワシミミズク", UNKNOWN_CARD, "ヤブガラ")
    mine = PlayerBoard(hand=hand, bonus=(UNKNOWN_CARD, UNKNOWN_CARD), food=(1, 1, 1, 1, 1), cubes=8)
    state = WingspanState(
        players=(mine, PlayerBoard()),
        to_move=0,
        first_player=0,
        round_index=0,
        feeder=(),
        tray=(),
        deck=(),
        discard=(),
        goals=all_goal_tiles()[:4],
        queue=(SetupTask(),),
        pending_setup=(0,),
    )
    move = KeepSetup(
        ("アメリカヤマセミ", "ヤブガラ"), (Food.FISH, Food.INVERTEBRATE, Food.SEED), UNKNOWN_CARD
    )
    tracker = Tracker()
    ticks = itertools.count()
    ex = WingspanExecutor(
        recognizer=Scripted(
            [
                "setup:keep",
                "setup:keep",
                "setup:keep",
                "setup:keep",
                "setup:keep",
                "setup:keep",
                "setup:bonus",
            ]
        ),  # type: ignore[arg-type]
        table=TABLE,
        tracker=tracker,
        sleep=lambda _s: None,
        clock=lambda: float(next(ticks)),
    )
    io = FakeIo()
    result = ex.execute(io, state, move)
    assert result.success, result.reason

    def at(action: InputAction) -> tuple[int, int]:
        return action.start.x, action.start.y  # type: ignore[union-attr]

    pressed = [at(a) for a in io.actions]
    assert pressed[0] == (
        layout.SETUP_CARD_X[1],
        layout.SETUP_CARD_Y,
    )  # アメリカヤマセミ(左から 2 番目)
    assert pressed[1] == (layout.SETUP_CARD_X[4], layout.SETUP_CARD_Y)  # ヤブガラ(5 番目)
    foods = [
        layout.SETUP_FOOD_X[layout.FOOD_ORDER_ON_SCREEN.index(f)]
        for f in ("fish", "invertebrate", "seed")
    ]
    assert [p[0] for p in pressed[2:5]] == foods and all(
        p[1] == layout.SETUP_FOOD_Y for p in pressed[2:5]
    )
    assert pressed[5] == layout.CONFIRM
    assert pressed[6] == (layout.SETUP_BONUS_X[0], layout.SETUP_BONUS_Y)  # 左のボーナス
    assert pressed[7] == layout.CONFIRM
    assert tracker.state is not None and tracker.state.pending_setup == ()
    assert tracker.state.players[0].hand == ("アメリカヤマセミ", "ヤブガラ")
    assert tracker.state.players[0].food == (
        1,
        1,
        1,
        0,
        0,
    )  # FOODS の並び(虫、種、魚、果実、ネズミ): 虫・種・魚 = 1
    assert replace(tracker.state).players[0].bonus == (UNKNOWN_CARD,)
