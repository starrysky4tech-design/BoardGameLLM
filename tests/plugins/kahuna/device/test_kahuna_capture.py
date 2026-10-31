"""実機(SHG11)の疎通テスト。`uv run pytest -m device` で実行する。

画面を取得するだけで、tap などの入力は送らない(ゲームの状態を変えない)。
"""

import pytest

from bglm.core.config import AndroidTarget
from bglm.infrastructure.adb_device import AdbDevice

SERIAL = "355092380222016"

pytestmark = pytest.mark.device


def test_connected_device_is_verified() -> None:
    AdbDevice(AndroidTarget(serial=SERIAL)).verify()


def test_capture_returns_a_full_screen_frame() -> None:
    frame = AdbDevice(AndroidTarget(serial=SERIAL)).capture()

    # 端末の向きによって 1080x2432 か 2432x1080 になる
    assert {frame.width, frame.height} == {1080, 2432}


def test_unknown_serial_is_not_verified() -> None:
    from bglm.core.errors import SourceLostError

    with pytest.raises(SourceLostError):
        AdbDevice(AndroidTarget(serial="no-such-device")).verify()
