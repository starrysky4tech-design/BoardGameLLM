"""プラグインの流れのテスト: 確認を受ける手、確定のタイミング、対応する手の判定、追跡の更新、再開の初期状態、プラグインの適合。

実機の観測(RESULT.md §9〜§14)に基づく。画面は偽(台本の画面名)と、保存画面(あれば)。
"""

import itertools
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import pytest

from bglm.core.models import Frame, InputAction, Point, Tap, UiKind
from bglm.core.protocols import GamePlugin
from bglm.plugins.wingspan import SupportedStrategy, WingspanPlugin, create_plugin, resume_from_env
from bglm.plugins.wingspan.logic.cards import default_table
from bglm.plugins.wingspan.logic.goals import GoalTile, all_goal_tiles
from bglm.plugins.wingspan.logic.models import (
    UNKNOWN_CARD,
    Food,
    Habitat,
    PlacedBird,
    Placement,
    PlayerBoard,
)
from bglm.plugins.wingspan.logic.rules import WingspanRules
from bglm.plugins.wingspan.logic.state import (
    AckConfirm,
    AckMatView,
    AckRound,
    AckSkip,
    AckTurnStart,
    ConvertCard,
    ConvertFoodTask,
    Decline,
    DrawTask,
    GainFoodTask,
    LayEgg,
    LayEggsTask,
    PlayBird,
    TakeDie,
    TakeTray,
    TuckCard,
    WingspanState,
)
from bglm.plugins.wingspan.vision import layout
from bglm.plugins.wingspan.vision.executor import WingspanExecutor, press
from bglm.plugins.wingspan.vision.recognizer import Resume, WingspanRecognizer
from bglm.plugins.wingspan.vision.tracker import Tracker

TABLE = default_table()
RULES = WingspanRules(TABLE)
F, G, W = Habitat.FOREST, Habitat.GRASSLAND, Habitat.WETLAND
DATA = Path("datasets/raw/wingspan/feasibility")
needs_real = pytest.mark.skipif(not (DATA / "290.png").exists(), reason="実画面が無い(Git 管理外)")


def board(forest=(), grass=(), wet=(), *, food=(0, 0, 0, 0, 0), hand=(), cubes=5) -> PlayerBoard:  # type: ignore[no-untyped-def]
    return PlayerBoard(
        rows=(tuple(forest), tuple(grass), tuple(wet)), food=food, hand=hand, cubes=cubes
    )


def state_of(*, mine: PlayerBoard | None = None, **changes) -> WingspanState:  # type: ignore[no-untyped-def]
    base = WingspanState(
        players=(mine or board(), board()),
        to_move=0,
        first_player=0,
        round_index=0,
        feeder=("invertebrate", "rodent"),
        tray=("ミサゴ", "", ""),
        deck=(UNKNOWN_CARD,) * 20,
        discard=(),
        goals=all_goal_tiles()[:4],
    )
    return replace(base, **changes)


class FakeIo:
    def __init__(self, image: np.ndarray | None = None) -> None:
        self.image = image if image is not None else np.zeros((1080, 2432, 3), dtype=np.uint8)
        self.actions: list[InputAction] = []

    def capture(self) -> Frame:
        return Frame.from_image(self.image, datetime(2026, 11, 14))

    def perform(self, action: InputAction) -> None:
        self.actions.append(action)


class Scripted:
    def __init__(self, names: list[str]) -> None:
        self.names, self.calls = names, 0

    def screen_name(self, _image: object) -> str:
        name = self.names[min(self.calls, len(self.names) - 1)]
        self.calls += 1
        return name


def executor(names: list[str], tracker: Tracker | None = None) -> WingspanExecutor:
    ticks = itertools.count()
    return WingspanExecutor(
        recognizer=Scripted(names),  # type: ignore[arg-type]
        table=TABLE,
        tracker=tracker,
        sleep=lambda _s: None,
        clock=lambda: float(next(ticks)),
    )


def is_press(action: InputAction, x: int, y: int) -> bool:
    return getattr(action, "start", None) == Point(x, y) == getattr(action, "end", None)


# ---- logic: 確認を受ける手 ----


def test_ack_state_offers_only_its_ack_move_and_clears_without_touching_the_board() -> None:
    expected = {
        "turn_start": AckTurnStart(),
        "confirm": AckConfirm(),
        "skip": AckSkip(),
        "round": AckRound(),
        "mat_view": AckMatView(),
    }
    for ack, move in expected.items():
        state = state_of(mine=board(food=(1, 0, 0, 0, 0)), ack=ack)
        assert RULES.legal_moves(state) == [move]
        after = RULES.apply(state, move)
        assert after.ack == "" and after.players == state.players and after.to_move == 0
        assert after.queue == state.queue  # 手番を進めない(settle しない)


def test_unknown_goal_scores_zero_without_crashing_the_round_end() -> None:
    mine = board(forest=[PlacedBird("コマツグミ", eggs=2)], cubes=0)
    state = state_of(mine=mine, goals=(GoalTile("unknown"),) * 4)
    state = state.with_player(1, replace(state.players[1], cubes=0))
    from bglm.plugins.wingspan.logic.rounds import end_round

    after = end_round(state, TABLE)
    assert after.players[0].goal_points == (0,) and after.round_index == 1


def test_unknown_bird_is_a_neutral_placeholder() -> None:
    placeholder = TABLE.bird(UNKNOWN_CARD)
    assert placeholder.points == 0 and placeholder.egg_limit == 0
    mine = board(forest=[PlacedBird(UNKNOWN_CARD, eggs=1)])
    assert RULES.scores(state_of(mine=mine))[0].total == 1  # 卵 1 点だけ。鳥の点は水増ししない


# ---- executor: 確定のタイミング ----


def test_take_die_waits_for_the_conversion_decision_when_a_card_can_be_discarded() -> None:
    # 森林の偶数列: 札を捨てて餌を足せる。最後の 1 個を取っても、確定は変換の決定(Decline)が担う
    mine = board(forest=[PlacedBird("コマツグミ")], hand=("ミサゴ",))
    state = state_of(mine=mine, queue=(GainFoodTask(1, convert=True),))
    io = FakeIo(cv2.imread(str(DATA / "290.png")) if (DATA / "290.png").exists() else None)
    if (DATA / "290.png").exists():
        result = executor(["prompt:pick_die"]).execute(io, state, TakeDie(0, Food.INVERTEBRATE))
        assert result.success and len(io.actions) == 1  # 確定しない
        no_card = state_of(
            mine=board(forest=[PlacedBird("コマツグミ")]), queue=(GainFoodTask(1, convert=True),)
        )
        io2 = FakeIo(cv2.imread(str(DATA / "290.png")))
        executor(["prompt:pick_die"]).execute(io2, no_card, TakeDie(0, Food.INVERTEBRATE))
        assert len(io2.actions) == 2  # 捨てる札が無ければ変換は無い。確定する


def test_lay_egg_waits_for_the_food_to_egg_decision_when_food_is_in_hand() -> None:
    mine = board(grass=[PlacedBird("コマツグミ")], food=(1, 0, 0, 0, 0))
    io = FakeIo()
    executor(["prompt:lay_eggs"]).execute(
        io, state_of(mine=mine, queue=(LayEggsTask(1, bonus=True),)), LayEgg(Placement(G, 0))
    )
    assert len(io.actions) == 1  # 餌があれば、変換の決定が確定を担う
    io2 = FakeIo()
    executor(["prompt:lay_eggs"]).execute(
        io2,
        state_of(mine=board(grass=[PlacedBird("コマツグミ")]), queue=(LayEggsTask(1, bonus=True),)),
        LayEgg(Placement(G, 0)),
    )
    assert len(io2.actions) == 2  # 餌が無ければ変換は無い。確定する


def test_draw_confirms_only_after_the_last_card_and_no_egg_conversion() -> None:
    mine = board(forest=[PlacedBird("コマツグミ", eggs=1)])
    # 2 枚引くうちの 1 枚目: 確定しない
    io = FakeIo()
    executor(["prompt:pick_card"]).execute(
        io, state_of(mine=mine, queue=(DrawTask(2),)), TakeTray(0)
    )
    assert len(io.actions) == 1
    # 最後の 1 枚で、卵を捨てて足せる: 確定しない(変換の決定が担う)
    io = FakeIo()
    executor(["prompt:pick_card"]).execute(
        io, state_of(mine=mine, queue=(DrawTask(1, bonus=True),)), TakeTray(0)
    )
    assert len(io.actions) == 1
    # 最後の 1 枚で、変換が無い: 確定する
    io = FakeIo()
    executor(["prompt:pick_card"]).execute(
        io,
        state_of(mine=board(forest=[PlacedBird("コマツグミ")]), queue=(DrawTask(1, bonus=True),)),
        TakeTray(0),
    )
    assert len(io.actions) == 2


# ---- executor: 確認を受ける手 ----


def test_ack_moves_press_the_right_places_and_only_on_the_right_screens() -> None:
    state = state_of()
    io = FakeIo()
    assert (
        executor(["dialog:turn_start", "dialog:turn_start"])
        .execute(io, state, AckTurnStart())
        .success
    )
    assert is_press(io.actions[0], 1216, 650)
    io = FakeIo()
    assert executor(["prompt:power_gain", "mat"]).execute(io, state, AckConfirm()).success
    assert is_press(io.actions[0], *layout.CONFIRM)
    io = FakeIo()
    assert executor(["dialog:round_score"]).execute(io, state, AckRound()).success
    assert is_press(io.actions[0], *layout.CONFIRM)
    io = FakeIo()
    ok = executor(["prompt:power_move", "confirm:skip", "confirm:skip"]).execute(
        io, state, AckSkip()
    )
    assert ok.success and is_press(io.actions[1], *layout.SKIP_CONFIRM)
    # 手番開始の確認は、そのダイアログのときだけ。盤のままなら押さない
    io = FakeIo()
    refused = executor(["mat"]).execute(io, state, AckTurnStart())
    assert not refused.success and io.actions == []


def test_executor_records_the_predicted_state_in_the_tracker_only_on_success() -> None:
    tracker = Tracker()
    state = state_of(ack="turn_start")
    assert executor(["dialog:turn_start"], tracker).execute(FakeIo(), state, AckTurnStart()).success
    assert tracker.state is not None and tracker.state.ack == ""
    stuck = Tracker()
    result = executor(["mat"], stuck).execute(FakeIo(), state_of(), AckTurnStart())
    assert not result.success and stuck.state is None  # 失敗した手の予測は置かない


def test_supports_marks_unmeasured_moves() -> None:
    ex = executor(["mat"])
    state = state_of(mine=board(hand=("クロズキンアメリカムシクイ", "コマツグミ")))
    assert ex.supports(state, TakeDie(0, Food.FISH)) and ex.supports(state, AckSkip())
    assert not ex.supports(state, ConvertCard("ミサゴ")) and not ex.supports(state, TuckCard("x"))
    single = PlayBird("クロズキンアメリカムシクイ", F, (2, 0, 0, 0, 0))
    two = PlayBird("コマツグミ", F, (0, 0, 0, 1, 0))  # 森林・草原の札(生息地の選択が出る)
    three = PlayBird("ヒメウタスズメ", F, (1, 1, 0, 0, 0))  # 3 つの生息地の札(3 択の位置は未測定)
    with_eggs = replace(single, egg_from=(Placement(F, 0),))
    assert ex.supports(state, single) and ex.supports(state, two) and ex.supports(state, with_eggs)
    assert not ex.supports(state, three)


def test_strategy_only_chooses_among_supported_moves() -> None:
    plugin = create_plugin()
    strategy = plugin.strategy()
    assert isinstance(strategy, SupportedStrategy)
    # 札を捨てて餌を足せる決定(ConvertFoodTask)。ConvertCard は位置を測っていないので選ばない
    state = replace(state_of(mine=board(hand=("ミサゴ",))), queue=(ConvertFoodTask(),))
    legal = RULES.legal_moves(state)
    assert ConvertCard("ミサゴ") in legal and Decline() in legal
    from bglm.core.models import TimeBudget

    chosen = strategy.choose(state, legal, TimeBudget(5.0))
    assert chosen == Decline()


# ---- 再開の初期状態 ----


def test_resume_from_env() -> None:
    got = resume_from_env({"WINGSPAN_HAND_SIZE": "5", "WINGSPAN_ROUND": "2", "WINGSPAN_BONUS": "2"})
    assert got == Resume(hand_size=5, round_no=2, bonus_count=2)
    assert resume_from_env({}) == Resume(hand_size=None, round_no=None, bonus_count=1)
    assert resume_from_env({"WINGSPAN_HAND_SIZE": "x"}).hand_size is None


def test_bootstrap_refuses_without_the_hand_size() -> None:
    rec = WingspanRecognizer(me=0, table=TABLE, read_lines=lambda *_: [], sleep=lambda _s: None)
    result = rec.observe(FakeIo(), None)
    assert result.ui.kind is UiKind.UNKNOWN and result.state is None


@needs_real
def test_bootstrap_builds_the_initial_state_from_the_board_and_zoomed_hand() -> None:
    rec = WingspanRecognizer(
        me=0,
        table=TABLE,
        read_lines=lambda *_: [],
        resume=Resume(hand_size=2, round_no=2, bonus_count=1),
        sleep=lambda _s: None,
    )
    # 本物の盤(290)。手札の拡大は、偽の入出力が「拡大 = 画面が変わる」を再現できないので、ここでは読み取りを差し替える
    import bglm.plugins.wingspan.vision.recognizer as module

    original = module.read_hand_names
    module.read_hand_names = lambda *_a, **_k: ["野鳥調査員", "コマツグミ"]  # type: ignore[assignment]
    try:
        result = rec.observe(FakeIo(cv2.imread(str(DATA / "290.png"))), None)
    finally:
        module.read_hand_names = original
    assert result.ui.kind is UiKind.PLAYABLE and result.state is not None
    state = result.state
    mine = state.players[0]
    assert state.round_index == 1 and mine.cubes == 6 and mine.food == (0, 3, 1, 0, 0)
    assert mine.bonus == ("野鳥調査員",) and mine.hand == ("コマツグミ",)
    assert mine.row(F)[0].eggs == 4  # 290: 森林のコマツグミに卵 4
    assert state.goals == (GoalTile("unknown"),) * 4  # 目的は読めない
    assert rec.tracker.state is state  # 追跡に置かれた


# ---- プラグインの適合 ----


def test_plugin_conforms_to_the_game_plugin_protocol() -> None:
    plugin = WingspanPlugin(resume=Resume(hand_size=5, round_no=2))
    assert isinstance(plugin, GamePlugin) and plugin.name == "wingspan"
    assert plugin.vlm_profile() is None
    assert isinstance(Tap(Point(0, 0)), Tap) and press(1, 2).hold_ms == 250


def test_last_round_score_ack_is_offered_even_in_a_terminal_state() -> None:
    # 実機: ラウンド 4 の採点の確認で、追跡が終局(round_index=4)になっても、確認を閉じる手は出す
    state = state_of(round_index=4, ack="round")
    assert state.terminal and RULES.legal_moves(state) == [AckRound()]
    assert RULES.legal_moves(replace(state, ack="")) == []


def test_mat_view_ack_presses_the_board_button_only_from_the_habitat_view() -> None:
    state = state_of(ack="mat_view")
    io = FakeIo()
    assert executor(["habitat", "mat"]).execute(io, state, AckMatView()).success
    assert is_press(io.actions[0], *layout.MAT_BUTTON)
    io = FakeIo()
    refused = executor(["mat"]).execute(io, state, AckMatView())
    assert not refused.success and io.actions == []  # 盤のときは押さない
