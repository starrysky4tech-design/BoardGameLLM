"""Android端末の画面取得と入力(ScreenSource と InputDriver の実装)。

`adb` は必ず `-s <シリアル>` を付けて呼ぶ。別の端末を操作する事故を防ぐため(docs/05)。
端末の削除・データ消去などの操作は、ここに入れない。
"""

import subprocess
from collections.abc import Callable
from datetime import datetime

import cv2
import numpy as np

from bglm.core.config import AndroidTarget
from bglm.core.errors import ConfigError, InputRejectedError, SourceLostError
from bglm.core.models import Drag, Frame, InputAction, KeyPress, Tap

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# (引数, タイムアウト秒) を受け取り、結果を返す。テストで差し替える
Runner = Callable[[list[str], float], "subprocess.CompletedProcess[bytes]"]


def _subprocess_runner(args: list[str], timeout: float) -> "subprocess.CompletedProcess[bytes]":
    return subprocess.run(args, capture_output=True, timeout=timeout, check=False)


class AdbDevice:
    """1台のAndroid端末。画面取得と、tap・swipeの入力を提供する。"""

    def __init__(
        self,
        target: AndroidTarget,
        runner: Runner = _subprocess_runner,
        clock: Callable[[], datetime] = datetime.now,
        timeout_sec: float = 30.0,
    ) -> None:
        if target.input_space != "display":
            # physical は回転の変換が要る。SHG11 は display で足りたため未実装(docs/03)
            raise ConfigError(f"input_space={target.input_space!r} は未対応。display のみ")
        self._serial = target.serial
        self._run = runner
        self._clock = clock
        self._timeout = timeout_sec

    def verify(self) -> None:
        """シリアルが接続中の端末に存在することを確かめる。無ければ SourceLostError。"""
        result = self._call(["adb", "devices"])
        lines = result.stdout.decode(errors="replace").splitlines()[1:]
        online = [line.split()[0] for line in lines if line.strip().endswith("device")]
        if self._serial not in online:
            raise SourceLostError(f"端末 {self._serial} が接続中の端末に無い: {online}")

    def capture(self) -> Frame:
        result = self._call(self._cmd("exec-out", "screencap", "-p"))
        data = result.stdout
        if not data.startswith(PNG_SIGNATURE):
            raise SourceLostError(f"画面の取得結果がPNGではない({len(data)}バイト)")
        image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise SourceLostError("画面のPNGを復号できない")
        return Frame.from_image(np.asarray(image, dtype=np.uint8), self._clock())

    def perform(self, action: InputAction) -> None:
        match action:
            case Tap(at=at):
                self._require_non_negative(at.x, at.y)
                self._shell("input", "tap", str(at.x), str(at.y))
            case Drag(start=start, end=end, duration_ms=duration_ms):
                self._require_non_negative(start.x, start.y, end.x, end.y)
                self._shell(
                    "input",
                    "swipe",
                    str(start.x),
                    str(start.y),
                    str(end.x),
                    str(end.y),
                    str(duration_ms),
                )
            case KeyPress():
                raise InputRejectedError("Androidではキー入力を使わない")

    def _cmd(self, *args: str) -> list[str]:
        return ["adb", "-s", self._serial, *args]

    def _shell(self, *args: str) -> None:
        self._call(self._cmd("shell", *args))

    def _call(self, args: list[str]) -> "subprocess.CompletedProcess[bytes]":
        try:
            result = self._run(args, self._timeout)
        except (subprocess.TimeoutExpired, OSError) as e:
            raise SourceLostError(f"adb を実行できない: {e}") from e
        if result.returncode != 0:
            detail = result.stderr.decode(errors="replace").strip()
            raise SourceLostError(f"adb が失敗(終了コード{result.returncode}): {detail}")
        return result

    @staticmethod
    def _require_non_negative(*values: int) -> None:
        if any(v < 0 for v in values):
            raise InputRejectedError(f"座標が負: {values}")
