"""Wingspan の認識のテスト。実画面(Git 管理外)で、画面種別ごとの返し方と、追跡との照合を確かめる。

OCR は、ほとんどのテストで偽物(何も読めない)を使う。読めない札名は追跡の名前を引き継ぐ(推測で変えない)ことも確かめる。
"""

from dataclasses import replace
from pathlib import Path

import cv2
import pytest

from bglm.core.models import UiKind
from bglm.plugins.wingspan.logic.board import TURNS_PER_ROUND
from bglm.plugins.wingspan.logic.cards import default_table
from bglm.plugins.wingspan.logic.goals import all_goal_tiles
from bglm.plugins.wingspan.logic.models import UNKNOWN_CARD, Habitat, PlacedBird, PlayerBoard
from bglm.plugins.wingspan.logic.rules import WingspanRules
from bglm.plugins.wingspan.logic.state import DrawTask, GainFoodTask, LayEggsTask, WingspanState
from bglm.plugins.wingspan.vision.ocr import JAPANESE_REC_MODEL, japanese_reader
from bglm.plugins.wingspan.vision.recognizer import WingspanRecognizer, _round_advanced

TABLE = default_table()
F, G, W = Habitat.FOREST, Habitat.GRASSLAND, Habitat.WETLAND
DATA = Path("datasets/raw/wingspan/feasibility")
needs_real = pytest.mark.skipif(not (DATA / "274.png").exists(), reason="実画面が無い(Git 管理外)")


def blind(*_args: object) -> list[str]:
    return []  # OCR が何も読めない(札名は追跡の名前を引き継ぐ)


def previous_state(**changes) -> WingspanState:  # type: ignore[no-untyped-def]
    mine = PlayerBoard(
        rows=((PlacedBird("コマツグミ", eggs=4),), (), (PlacedBird("アメリカヤマセミ"),)), cubes=6
    )
    theirs = PlayerBoard(rows=((PlacedBird(UNKNOWN_CARD),), (), ()), cubes=6)
    base = WingspanState(
        players=(mine, theirs),
        to_move=0,  # 既定は自分の手番(相手の手番の検査は、to_move=1 を渡す)
        first_player=1,
        round_index=0,
        feeder=("seed",),
        tray=("", "", ""),
        deck=(),
        discard=(),
        goals=all_goal_tiles()[:4],
    )
    return replace(base, **changes)


def recognizer(reader=blind) -> WingspanRecognizer:  # type: ignore[no-untyped-def]
    return WingspanRecognizer(me=0, table=TABLE, read_lines=reader)


def image(name: str):  # type: ignore[no-untyped-def]
    return cv2.imread(str(DATA / f"{name}.png"))


@needs_real
def test_clean_my_board_is_playable_and_updates_the_tracked_state() -> None:
    result = recognizer().recognize(image("290"), previous_state())
    assert result.ui.kind is UiKind.PLAYABLE and result.ui.screen == "my_turn"
    state = result.state
    assert state is not None
    # 290: キューブ 6、餌 = 魚 1・種 3、餌箱 = 虫・ネズミ・ネズミ
    assert state.players[0].cubes == 6
    assert state.players[0].food == (0, 3, 1, 0, 0)
    assert state.feeder == ("invertebrate", "rodent", "rodent")
    assert state.to_move == 0  # 自分の手番になった
    # 札名を読めなくても、追跡の名前を引き継ぎ、卵は画面から読む
    assert state.players[0].row(F)[0].name == "コマツグミ" and state.players[0].row(F)[0].eggs == 4
    assert state.players[0].row(W)[0].eggs == 0


@needs_real
def test_name_mismatch_with_the_tracked_state_stops() -> None:
    wrong = previous_state()
    board = wrong.players[0].with_row(F, (PlacedBird("ミサゴ", eggs=4),))
    result = recognizer(japanese_reader()).recognize(image("290"), wrong.with_player(0, board))
    assert result.ui.kind is UiKind.UNKNOWN and result.state is None
    assert "bird_mismatch:forest[0]" in result.low_confidence


@needs_real
def test_birds_decreasing_stops() -> None:
    state = previous_state()
    board = state.players[0].with_row(
        G, (PlacedBird("コマツグミ"),)
    )  # 草原に鳥がいたはずが、画面に無い
    result = recognizer().recognize(image("290"), state.with_player(0, board))
    assert result.ui.kind is UiKind.UNKNOWN
    assert "birds_decreased:grassland" in result.low_confidence


@needs_real
def test_pending_decision_with_a_clean_board_stops() -> None:
    state = replace(previous_state(), queue=(GainFoodTask(1),))
    result = recognizer().recognize(image("290"), state)
    assert result.ui.kind is UiKind.UNKNOWN and "decision_pending" in result.low_confidence


@needs_real
def test_no_previous_state_never_builds_a_state() -> None:
    result = recognizer().recognize(image("290"), None)
    assert result.state is None and result.ui.kind is UiKind.UNKNOWN
    assert result.low_confidence == ("no_previous_state",)


@needs_real
def test_dialogs_are_classified_by_their_text() -> None:
    if not JAPANESE_REC_MODEL.exists():
        pytest.skip("日本語の認識モデルが無い")
    rec = recognizer(japanese_reader(scale=2))
    start = rec.recognize(image("289"), previous_state())
    # 手番開始のダイアログは、閉じる操作が要る(確認を求める画面)。ack を立てた状態で PLAYABLE
    assert start.ui.kind is UiKind.PLAYABLE and start.ui.screen == "dialog:turn_start"
    assert start.state is not None and start.state.ack == "turn_start" and start.state.to_move == 0
    # 押してはいけないもの(ゲームのメニュー)は FORBIDDEN、終局の画面は GAME_OVER
    assert rec.recognize(image("266_probe"), previous_state()).ui.kind is UiKind.FORBIDDEN
    assert rec.recognize(image("176_final"), previous_state()).ui.kind is UiKind.GAME_OVER
    assert rec.recognize(image("178_menu"), previous_state()).ui.screen == "dialog:save_prompt"


@needs_real
def test_unreadable_dialog_is_unknown_not_waiting() -> None:
    # OCR が何も読めないダイアログは、種別を決めない(待ちとして扱わない)
    result = recognizer().recognize(image("289"), previous_state())
    assert result.ui.kind is UiKind.UNKNOWN and result.low_confidence == ("dialog_unknown",)


@needs_real
def test_opponent_turn_is_waiting() -> None:
    result = recognizer().recognize(image("302_opp_turn_1"), previous_state())
    assert result.ui.kind is UiKind.WAITING and result.ui.screen == "opponent_turn"


@needs_real
def test_habitat_view_asks_to_switch_to_the_board() -> None:
    # 新しい対局の既定は生息地の表示。実行する手は全体ボードの座標を前提にするので、切り替える確認の手を出す
    result = recognizer().recognize(image("016_my_turn"), previous_state())
    assert result.ui.kind is UiKind.PLAYABLE and result.ui.screen == "habitat"
    assert result.state is not None and result.state.ack == "mat_view"
    assert recognizer().recognize(image("016_my_turn"), None).ui.kind is UiKind.UNKNOWN


@needs_real
def test_prompt_screen_returns_the_tracked_state_with_the_prompt_kind() -> None:
    if not JAPANESE_REC_MODEL.exists():
        pytest.skip("日本語の認識モデルが無い")
    state = previous_state(to_move=0)
    state = replace(state, queue=(LayEggsTask(2),))  # 追跡している決定が、画面の案内と合う
    result = recognizer(japanese_reader()).recognize(image("275_lay"), state)
    assert result.ui.kind is UiKind.PLAYABLE and result.ui.screen == "prompt:lay_eggs"
    assert result.state is state  # 追跡の状態をそのまま返す
    # 追跡している決定と合わない「卵を置く」案内は、1 回ぶんの自由な選択(相手の能力で回ってきたもの)として扱う
    other = replace(state, queue=(GainFoodTask(1),))
    free = recognizer(japanese_reader()).recognize(image("275_lay"), other)
    assert free.ui.kind is UiKind.PLAYABLE
    assert free.state is not None and free.state.queue == (LayEggsTask(1),)


@needs_real
def test_opponent_board_updates_only_the_opponent() -> None:
    state = previous_state()
    result = recognizer().recognize(image("233_opp"), state)
    assert result.ui.kind is UiKind.WAITING and result.ui.screen == "opponent_board"
    assert result.state is not None
    assert result.state.players[0] == state.players[0]  # 自分の盤は触らない
    # 相手の盤を読んだ: 233_opp の右端は、キューブ 6、ネズミ 1(目視)。FOODS の並びは (虫, 種, 魚, 果実, ネズミ)
    assert result.state.players[1].food == (0, 0, 0, 0, 1)
    assert result.state.players[1].cubes == 6


def test_round_advances_when_cubes_jump_to_the_next_rounds_turn_count() -> None:
    state = previous_state(to_move=0)
    state = state.with_player(0, replace(state.players[0], cubes=1))
    assert _round_advanced(state, TURNS_PER_ROUND[1], 0)  # 1 → 7
    assert not _round_advanced(state, 5, 0)  # 5 は次のラウンドの手番数ではない
    assert not _round_advanced(state, None, 0)
    last = replace(state, round_index=3)
    assert not _round_advanced(last, 7, 0)  # 最後のラウンドの次は無い


@needs_real
def test_confirm_style_prompts_become_ack_states() -> None:
    # 314_pink_prompt: 桃色の能力の確認(「1 魚を共通在庫から獲得する」+ ✗/✓)。決定ではないので、確認を受ける手
    if not JAPANESE_REC_MODEL.exists():
        pytest.skip("日本語の認識モデルが無い")
    result = recognizer(japanese_reader()).recognize(image("314_pink_prompt"), previous_state())
    assert result.ui.kind is UiKind.PLAYABLE and result.ui.screen == "prompt:power_gain"
    assert result.state is not None and result.state.ack == "confirm"
    # 未実装の能力(別の生息地へ移す)は、スキップする手
    skip = recognizer(japanese_reader()).recognize(image("136_ok"), previous_state())
    assert skip.state is not None and skip.state.ack == "skip"


@needs_real
def test_round_score_dialog_ends_the_tracked_round_once() -> None:
    if not JAPANESE_REC_MODEL.exists():
        pytest.skip("日本語の認識モデルが無い")
    rec = recognizer(japanese_reader(scale=2))
    state = previous_state(to_move=0)
    state = state.with_player(0, replace(state.players[0], cubes=0)).with_player(
        1, replace(state.players[1], cubes=0)
    )
    first = rec.recognize(image("277_r1end"), state)
    assert first.state is not None and first.state.ack == "round"
    assert first.state.round_index == 1  # 追跡のラウンドが進んだ
    again = rec.recognize(image("277_r1end"), first.state)
    assert (
        again.state is not None and again.state.round_index == 1
    )  # 2 回目は進めない(キューブが満タン)


def test_turn_start_dialog_decrements_the_opponents_cubes_once() -> None:
    rec = recognizer()
    state = previous_state(to_move=1)  # 自分の手を終え、相手の手番(追跡)
    after = rec._turn_started(state)
    assert after.to_move == 0 and after.ack == "turn_start"
    assert after.players[1].cubes == state.players[1].cubes - 1
    again = rec._turn_started(
        after
    )  # 2 段目のダイアログ(残り n 手番)は、相手のキューブを減らさない
    assert again.players[1].cubes == after.players[1].cubes


@needs_real
def test_clean_board_while_the_tracked_turn_is_the_opponents_waits_for_the_dialog() -> None:
    # 確定の直後(砂時計が出る前)の盤だけの画面を、自分の手番と取り違えない(実機で、5 手目が誤って押された)
    state = previous_state(to_move=1)
    result = recognizer().recognize(image("290"), state)
    assert result.ui.kind is UiKind.WAITING and result.ui.screen == "opponent_turn"
    assert result.state is None
    mine = recognizer().recognize(image("290"), previous_state(to_move=0))
    assert mine.ui.kind is UiKind.PLAYABLE  # 追跡も自分の手番なら、読む


@needs_real
def test_unreadable_dialog_after_the_last_round_is_game_over() -> None:
    # 340_end_1: 最後のラウンドの採点の確認の直後。得点の演出の始まりで、文言が決まらない
    state = replace(previous_state(), round_index=4)
    result = recognizer().recognize(image("340_end_1"), state)
    assert result.ui.kind is UiKind.GAME_OVER
    assert recognizer().recognize(image("340_end_1"), previous_state()).ui.kind is UiKind.UNKNOWN


@needs_real
def test_os_toast_over_the_board_is_waited_out_not_a_stop() -> None:
    # 363_toast: 「実績を達成しました」が上端に重なる(実機で、鳥のプレイの直後に出た)。盤の判別は崩れるが、数秒で消える
    result = recognizer().recognize(image("363_toast"), previous_state())
    assert result.ui.kind is UiKind.WAITING and result.ui.screen == "toast"
    # 通知ではない不明な画面(メインメニュー)は、待たずに止める
    assert recognizer().recognize(image("002_menu"), previous_state()).ui.kind is UiKind.UNKNOWN


@needs_real
def test_free_choice_prompt_without_a_tracked_decision_becomes_a_single_decision() -> None:
    # 相手の鳥の能力(ノドアカハチドリ「各プレイヤーは餌箱から 1 個選んで獲得」)で、自分にも餌を選ぶ番が回ってきた。
    # 364_free_pick: 追跡している決定は無いが、案内「餌箱から餌を選んでください」と餌箱のダイスが出ている(実機)
    if not JAPANESE_REC_MODEL.exists():
        pytest.skip("日本語の認識モデルが無い")
    state = previous_state(to_move=1)  # 追跡では相手の手番
    result = recognizer(japanese_reader()).recognize(image("364_free_pick"), state)
    assert result.ui.kind is UiKind.PLAYABLE and result.ui.screen == "prompt:pick_die"
    assert result.state is not None and result.state.to_move == 0
    assert result.state.queue == (GainFoodTask(1),)
    assert result.state.feeder == ("invertebrate", "invertebrate", "seed")  # 画面の餌箱(虫・虫・種)


@needs_real
def test_lay_prompt_with_no_bird_to_lay_on_is_closed_by_confirming() -> None:
    # 368_lay_full: 鳥が満卵(3/3)なのに「産卵してください」が残っている。置き先が無いので、確定を押して閉じる
    if not JAPANESE_REC_MODEL.exists():
        pytest.skip("日本語の認識モデルが無い")
    full = PlayerBoard(rows=((PlacedBird("クロズキンアメリカムシクイ", eggs=3),), (), ()), cubes=4)
    state = previous_state(to_move=0)
    state = replace(state, players=(full, state.players[1]), queue=())
    result = recognizer(japanese_reader()).recognize(image("368_lay_full"), state)
    assert result.ui.kind is UiKind.PLAYABLE and result.state is not None
    assert result.state.ack == "confirm" and result.state.queue == ()


class SequenceIo:
    """最初に指定の画像、そのあとは真っ黒な画像を返す(入力を記録する)。"""

    def __init__(self, first) -> None:  # type: ignore[no-untyped-def]
        self.frames = [first]
        self.actions: list = []

    def capture(self):  # type: ignore[no-untyped-def]
        from datetime import datetime

        import numpy as np

        from bglm.core.models import Frame

        img = self.frames.pop(0) if self.frames else np.zeros((1080, 2432, 3), dtype=np.uint8)
        return Frame.from_image(img, datetime(2026, 11, 14))

    def perform(self, action) -> None:  # type: ignore[no-untyped-def]
        self.actions.append(action)


@needs_real
def test_bootstrap_confirms_a_power_gain_prompt_before_reading_the_board() -> None:
    # 381_now: 能力の獲得の確認(全てのプレイヤーは魚を獲得)。決定ではないので、確定を押して閉じる
    if not JAPANESE_REC_MODEL.exists():
        pytest.skip("日本語の認識モデルが無い")
    from bglm.core.models import Tap
    from bglm.plugins.wingspan.vision import layout

    io = SequenceIo(image("381_now"))
    rec = WingspanRecognizer(me=0, table=TABLE, read_lines=japanese_reader(), sleep=lambda _s: None)
    rec.observe(io, None)
    assert io.actions and isinstance(io.actions[0], Tap)
    assert (io.actions[0].at.x, io.actions[0].at.y) == layout.CONFIRM


@needs_real
def test_free_card_pick_reads_which_tray_cards_are_left_from_the_screen() -> None:
    # 393_now: 「1 枚カードを選ぶ」。右の 1 枚だけが明るい(他の 2 枠は取られた)。追跡の古いトレイ(3 枚)を使わない
    if not JAPANESE_REC_MODEL.exists():
        pytest.skip("日本語の認識モデルが無い")
    state = previous_state(to_move=0, tray=("?", "?", "?"))
    result = recognizer(japanese_reader()).recognize(image("393_now"), state)
    assert result.ui.kind is UiKind.PLAYABLE and result.state is not None
    assert result.state.tray == ("", "", "?")
    assert [
        m.index for m in WingspanRules(TABLE).legal_moves(result.state) if hasattr(m, "index")
    ] == [2]


@needs_real
def test_draw_from_deck_prompt_becomes_a_deck_draw_decision() -> None:
    # 463_draw_deck_prompt: 「1 枚の鳥を山札から引く。」山札だけが選べる(トレイは使えない)。山札を引く 1 手にする
    if not JAPANESE_REC_MODEL.exists():
        pytest.skip("日本語の認識モデルが無い")
    state = previous_state(to_move=0, deck=("?", "?"))
    result = recognizer(japanese_reader()).recognize(image("463_draw_deck_prompt"), state)
    assert result.ui.kind is UiKind.PLAYABLE and result.ui.screen == "prompt:draw_deck"
    assert result.state is not None and result.state.queue == (DrawTask(1),)
    assert result.state.tray == ("", "", "")
    legal = WingspanRules(TABLE).legal_moves(result.state)
    assert [type(m).__name__ for m in legal] == ["TakeDeck"]
