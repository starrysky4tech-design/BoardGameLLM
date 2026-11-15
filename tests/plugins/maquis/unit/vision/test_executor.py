"""MaquisExecutor のテスト。画面の種類と認識結果は偽で与え、押した座標と順序を確かめる。"""

from collections.abc import Iterator
from dataclasses import replace

import numpy as np
import pytest
from tests.plugins.maquis.support.helpers import ScriptedIo

from bglm.core.models import Tap
from bglm.plugins.maquis.logic.models import EndPhase, MaquisState, Phase, Place, Resolve
from bglm.plugins.maquis.logic.rules import MaquisRules, initial_state
from bglm.plugins.maquis.vision import executor as executor_module
from bglm.plugins.maquis.vision import layout
from bglm.plugins.maquis.vision.executor import MaquisExecutor
from bglm.plugins.maquis.vision.screens import ScreenKind


class FakeRecognizer:
    def __init__(self, states: list[MaquisState | None]) -> None:
        self._states = states
        self.calls = 0

    def recognize(self, io: object, image: object, previous: MaquisState | None) -> object:
        state = self._states[min(self.calls, len(self._states) - 1)]
        self.calls += 1
        return type("Rec", (), {"state": state})()


@pytest.fixture
def screens(monkeypatch: pytest.MonkeyPatch) -> list[ScreenKind]:
    """撮影のたびに、先頭から順に返す画面の種類(足りなければ最後を繰り返す)。"""
    script: list[ScreenKind] = []
    cursor: Iterator[int] = iter(range(10**6))

    def fake(image: object) -> ScreenKind:
        i = next(cursor)
        return script[min(i, len(script) - 1)]

    monkeypatch.setattr(executor_module, "classify_screen", fake)
    return script


def make(states: list[MaquisState | None]) -> tuple[MaquisExecutor, ScriptedIo]:
    io = ScriptedIo([np.zeros((1080, 2432, 3), dtype=np.uint8)])
    rules = MaquisRules()
    ex = MaquisExecutor(rules, FakeRecognizer(states), sleep=lambda s: None)  # type: ignore[arg-type]
    return ex, io


def taps(io: ScriptedIo) -> list[tuple[int, int]]:
    return [(a.at.x, a.at.y) for a in io.performed if isinstance(a, Tap)]


def test_place_taps_node_then_place_button(screens: list[ScreenKind]) -> None:
    state = initial_state()
    expected = MaquisRules().apply(state, Place("grocer"))
    screens += [ScreenKind.BOARD]
    ex, io = make([expected])
    result = ex.execute(io, state, Place("grocer"))  # type: ignore[arg-type]
    assert result.success
    assert taps(io) == [layout.NODE_CENTER["grocer"], layout.PLACE_BTN]


def test_place_on_mission_slot_taps_the_mission_button(screens: list[ScreenKind]) -> None:
    state = initial_state()
    expected = MaquisRules().apply(state, Place("mission_a"))
    screens += [ScreenKind.BOARD]
    ex, io = make([expected])
    assert ex.execute(io, state, Place("mission_a")).success is True  # type: ignore[arg-type]
    assert taps(io)[0] == layout.MISSION_BUTTON["mission_a"]


def test_resolve_taps_the_action_slot(screens: list[ScreenKind]) -> None:
    base = replace(initial_state(), phase=Phase.ACTION, unplaced=0, agents=("doctor",))
    move = Resolve("doctor", 0)
    expected = MaquisRules().apply(base, move)
    screens += [ScreenKind.BOARD]
    ex, io = make([expected])
    assert ex.execute(io, base, move).success  # type: ignore[arg-type]
    assert taps(io) == [layout.NODE_CENTER["doctor"], (layout.PLACE_BTN[0], layout.SLOT_Y[0])]


def test_refuses_when_not_on_the_board(screens: list[ScreenKind]) -> None:
    screens += [ScreenKind.UNKNOWN]
    ex, io = make([initial_state()])
    result = ex.execute(io, initial_state(), Place("grocer"))  # type: ignore[arg-type]
    assert not result.success
    assert result.reason == "not_board"
    assert taps(io) == []


def test_stops_if_a_dialog_appears_after_selecting(screens: list[ScreenKind]) -> None:
    screens += [ScreenKind.BOARD, ScreenKind.UNKNOWN]
    ex, io = make([initial_state()])
    result = ex.execute(io, initial_state(), Place("grocer"))  # type: ignore[arg-type]
    assert result.reason == "not_board_after_select"
    assert taps(io) == [layout.NODE_CENTER["grocer"]]  # 右列は押さない


def test_end_phase_presses_once_when_no_confirmation(screens: list[ScreenKind]) -> None:
    state = replace(initial_state(), unplaced=0, agents=("doctor",))
    expected = MaquisRules().apply(state, EndPhase())
    screens += [ScreenKind.BOARD]
    ex, io = make([expected])
    assert ex.execute(io, state, EndPhase()).success  # type: ignore[arg-type]
    assert taps(io) == [layout.END_BTN]


def test_end_phase_presses_confirm_only_when_dialog_is_shown(screens: list[ScreenKind]) -> None:
    state = replace(initial_state(), phase=Phase.ACTION, unplaced=0)
    expected = MaquisRules().apply(state, EndPhase())
    screens += [ScreenKind.BOARD, ScreenKind.CONFIRM, ScreenKind.BOARD]
    ex, io = make([expected])
    assert ex.execute(io, state, EndPhase()).success  # type: ignore[arg-type]
    assert taps(io) == [layout.END_BTN, layout.END_BTN]


def test_end_phase_that_ends_the_game_is_success(screens: list[ScreenKind]) -> None:
    state = replace(initial_state(), phase=Phase.ACTION, unplaced=0)
    screens += [ScreenKind.BOARD, ScreenKind.END_DEFEAT]
    ex, io = make([None])
    assert ex.execute(io, state, EndPhase()).success  # type: ignore[arg-type]


def test_fails_when_the_state_does_not_match(screens: list[ScreenKind]) -> None:
    screens += [ScreenKind.BOARD]
    ex, io = make([initial_state()])  # 配置後のはずが、変わっていない
    result = ex.execute(io, initial_state(), Place("grocer"))  # type: ignore[arg-type]
    assert not result.success
    assert result.reason == "verify_failed"


def test_never_taps_the_forbidden_button(screens: list[ScreenKind]) -> None:
    state = initial_state()
    screens += [ScreenKind.BOARD]
    ex, io = make([MaquisRules().apply(state, Place("cafe"))])
    ex.execute(io, state, Place("cafe"))  # type: ignore[arg-type]
    assert layout.END_FORBIDDEN not in taps(io)


def test_end_phase_waits_out_the_banner_without_pressing_again(screens: list[ScreenKind]) -> None:
    # 押した直後は、フェイズの帯で画面が判別できない(UNKNOWN)。消えたら盤。ボタンは1回だけ
    state = replace(initial_state(), unplaced=0, agents=("doctor",))
    expected = MaquisRules().apply(state, EndPhase())
    screens += [ScreenKind.BOARD, ScreenKind.UNKNOWN, ScreenKind.UNKNOWN, ScreenKind.BOARD]
    ex, io = make([expected])
    assert ex.execute(io, state, EndPhase()).success  # type: ignore[arg-type]
    assert taps(io) == [layout.END_BTN]


def test_end_phase_fails_if_the_screen_never_becomes_known(screens: list[ScreenKind]) -> None:
    state = replace(initial_state(), unplaced=0, agents=("doctor",))
    screens += [ScreenKind.BOARD, ScreenKind.UNKNOWN]
    ex, io = make([initial_state()])
    result = ex.execute(io, state, EndPhase())  # type: ignore[arg-type]
    assert result.reason == "unexpected_screen:unknown"
    assert taps(io) == [layout.END_BTN]


def test_morale_drop_at_turn_change_does_not_fail_the_verification(
    screens: list[ScreenKind],
) -> None:
    state = replace(initial_state(), phase=Phase.ACTION, unplaced=0)
    expected = MaquisRules().apply(state, EndPhase())
    lowered = replace(
        expected, resources=replace(expected.resources, morale=expected.resources.morale - 1)
    )
    screens += [ScreenKind.BOARD]
    ex, io = make([lowered])
    assert ex.execute(io, state, EndPhase()).success  # type: ignore[arg-type]
