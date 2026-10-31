"""プラグインに渡す唯一の入出力の窓口(GameIo の実行用とリプレイ用)。

取得した画像と送った入力をすべて記録する。AgentRunner は1手ごとに take_frames / take_actions
で取り出して StepRecord にする。プラグインは1手で何枚の画面を読み何回操作するかを自由に決められ、
AgentRunner はその違いを知らずに済む。
"""

from collections.abc import Callable, Sequence

from bglm.core.errors import ReplayExhaustedError, UserAbortError
from bglm.core.models import Frame, InputAction
from bglm.core.protocols import InputDriver, ScreenSource


class _Recording:
    def __init__(self) -> None:
        self._frames: list[Frame] = []
        self._actions: list[InputAction] = []

    def take_frames(self) -> list[Frame]:
        """前回から取得した画像を取り出す。取り出すと空になる。"""
        frames, self._frames = self._frames, []
        return frames

    def take_actions(self) -> list[InputAction]:
        """前回から送った入力を取り出す。取り出すと空になる。"""
        actions, self._actions = self._actions, []
        return actions


class LiveGameIo(_Recording):
    """実機に入出力する。入力の直前に緊急停止を確認し、要求されていれば入力を送らず止める。"""

    def __init__(
        self,
        source: ScreenSource,
        driver: InputDriver,
        abort_requested: Callable[[], bool],
    ) -> None:
        super().__init__()
        self._source = source
        self._driver = driver
        self._abort_requested = abort_requested

    def capture(self) -> Frame:
        frame = self._source.capture()
        self._frames.append(frame)
        return frame

    def perform(self, action: InputAction) -> None:
        if self._abort_requested():
            raise UserAbortError("緊急停止が要求された")
        self._driver.perform(action)
        self._actions.append(action)


class ReplayGameIo(_Recording):
    """保存した画像を順に返す。入力は記録するだけで、どこにも送らない。"""

    def __init__(self, frames: Sequence[Frame]) -> None:
        super().__init__()
        self._queue = list(frames)
        self._position = 0

    def capture(self) -> Frame:
        if self._position >= len(self._queue):
            raise ReplayExhaustedError(f"リプレイ用の画像{len(self._queue)}枚を使い切った")
        frame = self._queue[self._position]
        self._position += 1
        self._frames.append(frame)
        return frame

    def perform(self, action: InputAction) -> None:
        self._actions.append(action)


class DryRunDriver:
    """`--dry-run` 用。入力をどこにも送らない(GameIo が送ったはずの入力として記録する)。"""

    def perform(self, action: InputAction) -> None:
        return None
