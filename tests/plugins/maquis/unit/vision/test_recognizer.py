"""Maquis の認識(前の状態との照合、山札の更新、終局・想定外の画面)のテスト。

盤の画像は、4局目(2026-11-11)の実画面(Git管理外。無ければ飛ばす)。山札の画面は開かず、
引かれたカードを偽の DeckReader で与える(カードの読み取りは test_recorded_screens)。
"""

import pytest
from tests.plugins.maquis.support.helpers import (
    FakeDeckReader,
    ScriptedIo,
    frame_path,
    load_frame_image,
)

from bglm.core.models import UiKind
from bglm.plugins.maquis.logic.models import MaquisState, Phase
from bglm.plugins.maquis.logic.patrol import PatrolCard
from bglm.plugins.maquis.logic.rules import MaquisRules, initial_state
from bglm.plugins.maquis.vision.deck_reader import DiscardRead
from bglm.plugins.maquis.vision.recognizer import MaquisRecognizer

# 引かれたカード(4局目の山札の画面は記録していないので、巡回の出た地点と矛盾しないカードを与える)
CARD_RADIO_A: PatrolCard = ("radio_a", "parade_street", "grocer")  # 無線Aに出現
CARD_RADIO_B: PatrolCard = ("radio_b", "grocer", "black_market")  # 無線Bに出現
CARD_FENCE: PatrolCard = ("black_market_fence", "parade_street", "slums")  # 故買屋に出現


def recognizer(reader: FakeDeckReader) -> MaquisRecognizer:
    return MaquisRecognizer(deck_reader=reader)  # type: ignore[arg-type]


def observe(
    reader: FakeDeckReader, name: str, previous: MaquisState | None
) -> tuple[MaquisState | None, UiKind, tuple[str, ...]]:
    image = load_frame_image(name)
    rec = recognizer(reader).recognize(ScriptedIo([image]), image, previous)  # type: ignore[arg-type]
    return rec.state, rec.ui.kind, rec.low_confidence


def need(*names: str) -> None:
    missing = [n for n in names if not frame_path(n).exists()]
    if missing:
        pytest.skip(f"記録画面が無い(Git管理外): {missing}")


def test_first_observation_is_the_start_of_a_new_game() -> None:
    need("game_001")
    reader = FakeDeckReader(DiscardRead(None, 0.0, problem="never"))
    state, kind, _ = observe(reader, "game_001", None)
    assert kind is UiKind.PLAYABLE
    assert state is not None
    assert (state.turn, state.phase, state.unplaced, state.agents_total) == (
        1,
        Phase.PLACEMENT,
        3,
        3,
    )
    assert state.deck.size() == 10
    assert reader.calls == 0  # 巡回が出ていないので、山札の画面は開かない


def test_a_placement_adds_the_agent_and_draws_the_card_that_matches_the_patrol() -> None:
    # 4局目 ターン1: 食料品店に置いた → 無線Aに巡回が出現(ログ)
    need("game_001", "y_p1")
    reader = FakeDeckReader(DiscardRead(CARD_RADIO_A, 1.0))
    state, kind, _ = observe(reader, "y_p1", initial_state())
    assert kind is UiKind.PLAYABLE
    assert state is not None
    assert state.agents == ("grocer",)
    assert state.patrols == {"radio_a"}
    assert state.unplaced == 2
    assert state.deck.size() == 9
    assert state.deck.count(CARD_RADIO_A) == 0
    assert reader.calls == 1


def test_three_placements_in_a_row_follow_the_runner_one_step_at_a_time() -> None:
    need("y_p1", "y_p2", "y_p3")
    state: MaquisState | None = initial_state()
    for name, card in (("y_p1", CARD_RADIO_A), ("y_p2", CARD_RADIO_B), ("y_p3", CARD_FENCE)):
        state, kind, low = observe(FakeDeckReader(DiscardRead(card, 1.0)), name, state)
        assert kind is UiKind.PLAYABLE, (name, low)
        assert state is not None
    assert state is not None
    assert state.agents == ("cafe", "doctor", "grocer")
    assert state.patrols == {"radio_a", "radio_b", "black_market_fence"}
    assert state.deck.size() == 7
    assert MaquisRules().legal_moves(state)  # 3人を置き終えたので、終了だけが合法手


def test_a_card_that_contradicts_the_patrol_stops_the_run() -> None:
    # 巡回は無線Aに出たのに、読んだカードは故買屋に出るもの → 読み取りかルールの誤り。止まる
    need("y_p1")
    state, kind, low = observe(
        FakeDeckReader(DiscardRead(CARD_FENCE, 1.0)), "y_p1", initial_state()
    )
    assert state is None
    assert kind is UiKind.UNKNOWN
    assert low == ("card_mismatch",)


def test_an_unreadable_discard_card_stops_the_run() -> None:
    need("y_p1")
    reader = FakeDeckReader(DiscardRead(None, 0.4, problem="unreadable_card"))
    state, kind, low = observe(reader, "y_p1", initial_state())
    assert (state, kind, low) == (None, UiKind.UNKNOWN, ("unreadable_card",))


def test_two_new_patrols_at_once_cannot_be_matched_to_cards() -> None:
    # 2人を続けて置いた画面(前の状態が2手前)。巡回が2つ増え、どのカードか決まらない
    need("y_p2")
    reader = FakeDeckReader(DiscardRead(CARD_RADIO_B, 1.0))
    state, kind, low = observe(reader, "y_p2", initial_state())
    assert (state, kind, low) == (None, UiKind.UNKNOWN, ("missed_draws",))
    assert reader.calls == 0


def test_a_board_three_moves_away_is_not_adopted() -> None:
    # 前の状態から 3手先の盤は、照合しない(待って読み直す。続けば止まる)
    need("y_p3")
    state, kind, low = observe(
        FakeDeckReader(DiscardRead(CARD_FENCE, 1.0)), "y_p3", initial_state()
    )
    assert (state, kind, low) == (None, UiKind.WAITING, ("no_matching_move",))


def test_the_defeat_dialog_returns_a_lost_state() -> None:
    need("x_t1_end2")
    previous = initial_state()
    state, kind, _ = observe(FakeDeckReader(DiscardRead(None, 0.0)), "x_t1_end2", previous)
    assert kind is UiKind.GAME_OVER
    assert state is not None
    assert MaquisRules().outcome(state) == "lose"


@pytest.mark.parametrize("name", ["m_menu", "g_deck_05", "r_t3", "rules_01", "m_pause"])
def test_other_screens_are_unknown_and_send_no_input(name: str) -> None:
    need(name)
    image = load_frame_image(name)
    io = ScriptedIo([image])
    reader = FakeDeckReader(DiscardRead(None, 0.0))
    rec = recognizer(reader).recognize(io, image, initial_state())  # type: ignore[arg-type]
    assert rec.ui.kind is UiKind.UNKNOWN
    assert rec.state is None
    assert io.performed == []
    assert reader.calls == 0


def test_an_unknown_mission_is_unknown_not_waiting() -> None:
    # 見たことの無い任務(暗殺)は、待っても直らないので UNKNOWN(止まる)
    need("s_p3")
    state, kind, low = observe(FakeDeckReader(DiscardRead(None, 0.0)), "s_p3", initial_state())
    assert (state, kind) == (None, UiKind.UNKNOWN)
    assert low == ("mission_unknown:mission_b",)
