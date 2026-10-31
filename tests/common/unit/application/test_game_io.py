from datetime import datetime

import numpy as np
import pytest

from bglm.application.game_io import LiveGameIo, ReplayGameIo
from bglm.core.errors import InputRejectedError, ReplayExhaustedError, UserAbortError
from bglm.core.models import Frame, InputAction, KeyPress, Point, Tap

NOW = datetime(2026, 10, 30, 12, 0, 0)


def frame(value: int) -> Frame:
    return Frame.from_image(np.full((4, 4, 3), value, dtype=np.uint8), NOW)


class FakeSource:
    def __init__(self, frames: list[Frame]) -> None:
        self.frames = frames
        self.captures = 0

    def capture(self) -> Frame:
        result = self.frames[self.captures]
        self.captures += 1
        return result


class FakeDriver:
    def __init__(self) -> None:
        self.performed: list[InputAction] = []
        self.error: Exception | None = None

    def perform(self, action: InputAction) -> None:
        if self.error is not None:
            raise self.error
        self.performed.append(action)


class TestLiveGameIo:
    def test_capture_returns_and_records_frames(self) -> None:
        a, b = frame(1), frame(2)
        io = LiveGameIo(FakeSource([a, b]), FakeDriver(), lambda: False)

        assert io.capture() is a
        assert io.capture() is b
        assert io.take_frames() == [a, b]

    def test_take_frames_empties_the_record(self) -> None:
        io = LiveGameIo(FakeSource([frame(1)]), FakeDriver(), lambda: False)
        io.capture()

        io.take_frames()

        assert io.take_frames() == []

    def test_perform_forwards_and_records_actions(self) -> None:
        driver = FakeDriver()
        io = LiveGameIo(FakeSource([]), driver, lambda: False)
        tap = Tap(Point(1, 2))

        io.perform(tap)

        assert driver.performed == [tap]
        assert io.take_actions() == [tap]
        assert io.take_actions() == []

    def test_abort_before_perform_sends_nothing(self) -> None:
        driver = FakeDriver()
        io = LiveGameIo(FakeSource([]), driver, lambda: True)

        with pytest.raises(UserAbortError):
            io.perform(Tap(Point(1, 2)))

        assert driver.performed == []
        assert io.take_actions() == []

    def test_abort_is_checked_on_every_perform(self) -> None:
        flag = {"abort": False}
        driver = FakeDriver()
        io = LiveGameIo(FakeSource([]), driver, lambda: flag["abort"])
        io.perform(Tap(Point(1, 1)))

        flag["abort"] = True
        with pytest.raises(UserAbortError):
            io.perform(Tap(Point(2, 2)))

        assert driver.performed == [Tap(Point(1, 1))]

    def test_capture_does_not_check_abort(self) -> None:
        io = LiveGameIo(FakeSource([frame(1)]), FakeDriver(), lambda: True)

        assert io.capture().width == 4

    def test_rejected_input_is_not_recorded_as_sent(self) -> None:
        driver = FakeDriver()
        driver.error = InputRejectedError("前面にない")
        io = LiveGameIo(FakeSource([]), driver, lambda: False)

        with pytest.raises(InputRejectedError):
            io.perform(KeyPress("e"))

        assert io.take_actions() == []


class TestReplayGameIo:
    def test_returns_frames_in_order(self) -> None:
        a, b = frame(1), frame(2)
        io = ReplayGameIo([a, b])

        assert [io.capture(), io.capture()] == [a, b]
        assert io.take_frames() == [a, b]

    def test_exhausted_raises(self) -> None:
        io = ReplayGameIo([frame(1)])
        io.capture()

        with pytest.raises(ReplayExhaustedError):
            io.capture()

    def test_empty_replay_raises_on_first_capture(self) -> None:
        with pytest.raises(ReplayExhaustedError):
            ReplayGameIo([]).capture()

    def test_perform_records_without_sending(self) -> None:
        io = ReplayGameIo([])
        tap = Tap(Point(5, 5))

        io.perform(tap)

        assert io.take_actions() == [tap]

    def test_perform_ignores_abort_because_nothing_is_sent(self) -> None:
        io = ReplayGameIo([])

        io.perform(KeyPress("e"))

        assert io.take_actions() == [KeyPress("e")]
