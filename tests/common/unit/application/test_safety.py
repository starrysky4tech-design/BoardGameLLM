from typing import Any

import pytest
from tests.common.support.fake_game import playable, rec

from bglm.application.safety import AbortFlag, KeyboardAbortWatcher, SafetyGuard
from bglm.core.config import RunnerConfig
from bglm.core.models import StopReason, UiKind


def guard(**overrides: Any) -> SafetyGuard:
    return SafetyGuard(RunnerConfig(**overrides), AbortFlag())


class TestAbortFlag:
    def test_starts_clear_and_can_be_requested(self) -> None:
        flag = AbortFlag()
        assert not flag.is_set()

        flag.request()

        assert flag.is_set()

    def test_clear_resets(self) -> None:
        flag = AbortFlag()
        flag.request()

        flag.clear()

        assert not flag.is_set()

    def test_guard_reflects_the_flag(self) -> None:
        flag = AbortFlag()
        g = SafetyGuard(RunnerConfig(), flag)

        flag.request()

        assert g.abort_requested()


class TestCheckUi:
    @pytest.mark.parametrize(
        ("kind", "state", "expected"),
        [
            (UiKind.FORBIDDEN, None, StopReason.FORBIDDEN_SCREEN),
            (UiKind.UNKNOWN, None, StopReason.UNKNOWN_SCREEN),
            (UiKind.PLAYABLE, None, StopReason.LOW_CONFIDENCE),
            (UiKind.PLAYABLE, 0, None),
            (UiKind.WAITING, None, None),
            (UiKind.GAME_OVER, None, None),
        ],
    )
    def test_by_kind(self, kind: UiKind, state: int | None, expected: StopReason | None) -> None:
        assert guard().check_ui(rec(kind, state=state)) is expected

    @pytest.mark.parametrize(
        ("confidence", "expected"),
        [
            (0.0, StopReason.LOW_CONFIDENCE),
            (0.79, StopReason.LOW_CONFIDENCE),
            (0.8, None),
            (1.0, None),
        ],
    )
    def test_confidence_threshold_boundary(
        self, confidence: float, expected: StopReason | None
    ) -> None:
        assert guard().check_ui(playable(0, confidence=confidence)) is expected

    def test_threshold_is_configurable(self) -> None:
        g = guard(confidence_threshold=0.95)

        assert g.check_ui(playable(0, confidence=0.9)) is StopReason.LOW_CONFIDENCE

    def test_forbidden_screen_stops_even_with_full_confidence(self) -> None:
        assert guard().check_ui(rec(UiKind.FORBIDDEN, state=1, confidence=1.0)) is not None


class TestCheckProgress:
    def check(self, g: SafetyGuard, **kwargs: Any) -> StopReason | None:
        base = {"steps_done": 0, "repeated": 0, "unchanged": 0, "waited_sec": 0.0}
        return g.check_progress(**{**base, **kwargs})

    def test_nothing_to_stop(self) -> None:
        assert self.check(guard()) is None

    @pytest.mark.parametrize(("steps", "expected"), [(999, None), (1000, StopReason.STEP_LIMIT)])
    def test_step_limit_boundary(self, steps: int, expected: StopReason | None) -> None:
        assert self.check(guard(step_limit=1000), steps_done=steps) is expected

    @pytest.mark.parametrize(("n", "expected"), [(1, None), (2, StopReason.NO_SCREEN_CHANGE)])
    def test_unchanged_limit_boundary(self, n: int, expected: StopReason | None) -> None:
        assert self.check(guard(unchanged_limit=2), unchanged=n) is expected

    @pytest.mark.parametrize(("n", "expected"), [(2, None), (3, StopReason.REPEATED_STATE)])
    def test_repeated_state_boundary(self, n: int, expected: StopReason | None) -> None:
        assert self.check(guard(repeated_state_limit=3), repeated=n) is expected

    @pytest.mark.parametrize(
        ("waited", "expected"), [(300.0, None), (300.1, StopReason.NO_SCREEN_CHANGE)]
    )
    def test_wait_limit_boundary(self, waited: float, expected: StopReason | None) -> None:
        assert self.check(guard(wait_limit_sec=300.0), waited_sec=waited) is expected

    def test_step_limit_takes_precedence(self) -> None:
        g = guard(step_limit=5)

        assert self.check(g, steps_done=5, repeated=9, unchanged=9) is StopReason.STEP_LIMIT

    def test_unchanged_takes_precedence_over_repeated(self) -> None:
        assert self.check(guard(), repeated=9, unchanged=9) is StopReason.NO_SCREEN_CHANGE


class FakeKey:
    def __init__(self, name: str | None = None, char: str | None = None) -> None:
        self.name = name
        self.char = char


class FakeListener:
    def __init__(self, on_press: Any) -> None:
        self.on_press = on_press
        self.started = 0
        self.stopped = 0

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1


def make_watcher(key_name: str = "f12") -> tuple[KeyboardAbortWatcher, AbortFlag, FakeListener]:
    flag = AbortFlag()
    holder: list[FakeListener] = []

    def factory(on_press: Any) -> FakeListener:
        holder.append(FakeListener(on_press))
        return holder[0]

    return KeyboardAbortWatcher(flag, key_name, factory), flag, holder[0]


class TestKeyboardAbortWatcher:
    def test_start_and_stop_are_forwarded(self) -> None:
        watcher, _, listener = make_watcher()

        watcher.start()
        watcher.stop()

        assert (listener.started, listener.stopped) == (1, 1)

    def test_configured_special_key_requests_abort(self) -> None:
        _, flag, listener = make_watcher("f12")

        listener.on_press(FakeKey(name="f12"))

        assert flag.is_set()

    def test_other_key_does_not_request_abort(self) -> None:
        _, flag, listener = make_watcher("f12")

        listener.on_press(FakeKey(name="f11"))
        listener.on_press(FakeKey(char="a"))
        listener.on_press(FakeKey())

        assert not flag.is_set()

    def test_key_name_is_case_insensitive(self) -> None:
        _, flag, listener = make_watcher("F12")

        listener.on_press(FakeKey(name="f12"))

        assert flag.is_set()

    def test_character_key_can_be_configured(self) -> None:
        _, flag, listener = make_watcher("q")

        listener.on_press(FakeKey(char="Q"))

        assert flag.is_set()


def test_real_pynput_listener_can_be_created_without_starting() -> None:
    """既定のファクトリが pynput のリスナーを作れること(フックはまだ張らない)。"""
    watcher = KeyboardAbortWatcher(AbortFlag(), "f12")

    assert watcher is not None
