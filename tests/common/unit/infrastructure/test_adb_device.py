import subprocess
from datetime import datetime

import cv2
import numpy as np
import pytest

from bglm.core.config import AndroidTarget
from bglm.core.errors import ConfigError, InputRejectedError, SourceLostError
from bglm.core.models import Drag, KeyPress, Point, Tap
from bglm.infrastructure.adb_device import AdbDevice

SERIAL = "355092380222016"
NOW = datetime(2026, 10, 30, 12, 0, 0)


def png_bytes(height: int = 20, width: int = 30) -> bytes:
    image = np.full((height, width, 3), 7, dtype=np.uint8)
    ok, buffer = cv2.imencode(".png", image)
    assert ok
    return buffer.tobytes()


class FakeRunner:
    """adb の呼び出しを記録し、あらかじめ決めた結果を返す。"""

    def __init__(self, stdout: bytes = b"", returncode: int = 0, stderr: bytes = b"") -> None:
        self.calls: list[list[str]] = []
        self.timeouts: list[float] = []
        self._result = subprocess.CompletedProcess([], returncode, stdout, stderr)
        self.raises: Exception | None = None

    def __call__(self, args: list[str], timeout: float) -> "subprocess.CompletedProcess[bytes]":
        self.calls.append(args)
        self.timeouts.append(timeout)
        if self.raises is not None:
            raise self.raises
        return self._result


def make_device(runner: FakeRunner) -> AdbDevice:
    return AdbDevice(AndroidTarget(serial=SERIAL), runner=runner, clock=lambda: NOW)


class TestCapture:
    def test_decodes_png_into_frame(self) -> None:
        device = make_device(FakeRunner(stdout=png_bytes(height=20, width=30)))

        frame = device.capture()

        assert (frame.width, frame.height) == (30, 20)
        assert frame.captured_at == NOW

    def test_command_targets_the_serial(self) -> None:
        runner = FakeRunner(stdout=png_bytes())

        make_device(runner).capture()

        assert runner.calls == [["adb", "-s", SERIAL, "exec-out", "screencap", "-p"]]

    def test_non_png_output_raises_source_lost(self) -> None:
        device = make_device(FakeRunner(stdout=b"error: device offline"))

        with pytest.raises(SourceLostError):
            device.capture()

    def test_empty_output_raises_source_lost(self) -> None:
        with pytest.raises(SourceLostError):
            make_device(FakeRunner(stdout=b"")).capture()

    def test_truncated_png_raises_source_lost(self) -> None:
        with pytest.raises(SourceLostError):
            make_device(FakeRunner(stdout=png_bytes()[:40])).capture()

    def test_nonzero_exit_raises_source_lost_with_stderr(self) -> None:
        device = make_device(FakeRunner(returncode=1, stderr=b"device not found"))

        with pytest.raises(SourceLostError, match="device not found"):
            device.capture()

    def test_timeout_raises_source_lost(self) -> None:
        runner = FakeRunner()
        runner.raises = subprocess.TimeoutExpired(cmd="adb", timeout=30)

        with pytest.raises(SourceLostError):
            make_device(runner).capture()

    def test_missing_adb_binary_raises_source_lost(self) -> None:
        runner = FakeRunner()
        runner.raises = FileNotFoundError("adb")

        with pytest.raises(SourceLostError):
            make_device(runner).capture()

    def test_timeout_is_passed_to_runner(self) -> None:
        runner = FakeRunner(stdout=png_bytes())
        device = AdbDevice(AndroidTarget(serial=SERIAL), runner=runner, timeout_sec=5.0)

        device.capture()

        assert runner.timeouts == [5.0]


class TestVerify:
    DEVICES = f"List of devices attached\n{SERIAL}\tdevice\n".encode()

    def test_connected_serial_passes(self) -> None:
        make_device(FakeRunner(stdout=self.DEVICES)).verify()

    def test_missing_serial_raises(self) -> None:
        other = b"List of devices attached\nABCDEF\tdevice\n"

        with pytest.raises(SourceLostError, match=SERIAL):
            make_device(FakeRunner(stdout=other)).verify()

    def test_offline_device_raises(self) -> None:
        offline = f"List of devices attached\n{SERIAL}\toffline\n".encode()

        with pytest.raises(SourceLostError):
            make_device(FakeRunner(stdout=offline)).verify()

    def test_no_devices_raises(self) -> None:
        with pytest.raises(SourceLostError):
            make_device(FakeRunner(stdout=b"List of devices attached\n\n")).verify()


class TestPerform:
    def test_tap_uses_serial_and_display_coordinates(self) -> None:
        runner = FakeRunner()

        make_device(runner).perform(Tap(Point(1252, 486)))

        assert runner.calls == [["adb", "-s", SERIAL, "shell", "input", "tap", "1252", "486"]]

    def test_tap_at_origin_is_allowed(self) -> None:
        runner = FakeRunner()

        make_device(runner).perform(Tap(Point(0, 0)))

        assert len(runner.calls) == 1

    def test_drag_becomes_swipe_with_duration(self) -> None:
        runner = FakeRunner()

        make_device(runner).perform(Drag(Point(1, 2), Point(3, 4), duration_ms=400))

        assert runner.calls == [
            ["adb", "-s", SERIAL, "shell", "input", "swipe", "1", "2", "3", "4", "400"]
        ]

    def test_key_press_is_rejected_without_calling_adb(self) -> None:
        runner = FakeRunner()

        with pytest.raises(InputRejectedError):
            make_device(runner).perform(KeyPress("e"))

        assert runner.calls == []

    @pytest.mark.parametrize("point", [Point(-1, 5), Point(5, -1)])
    def test_negative_tap_is_rejected_without_calling_adb(self, point: Point) -> None:
        runner = FakeRunner()

        with pytest.raises(InputRejectedError):
            make_device(runner).perform(Tap(point))

        assert runner.calls == []

    def test_negative_drag_end_is_rejected(self) -> None:
        runner = FakeRunner()

        with pytest.raises(InputRejectedError):
            make_device(runner).perform(Drag(Point(1, 1), Point(-1, 1), duration_ms=100))

        assert runner.calls == []

    def test_failed_adb_raises_source_lost(self) -> None:
        with pytest.raises(SourceLostError):
            make_device(FakeRunner(returncode=1)).perform(Tap(Point(1, 1)))


def test_physical_input_space_is_rejected_at_construction() -> None:
    target = AndroidTarget(serial=SERIAL, input_space="physical")

    with pytest.raises(ConfigError):
        AdbDevice(target, runner=FakeRunner())
