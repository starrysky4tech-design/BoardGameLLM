"""緊急停止と、停止条件の判定。

判定(SafetyGuard)は純粋な関数に近く、カウンタは AgentRunner が持つ。
緊急停止キーの監視は別スレッドで行い、実行ループが処理中でも検知する。
"""

import threading
from collections.abc import Callable
from typing import Any, Protocol

from bglm.core.config import RunnerConfig
from bglm.core.models import Recognition, StopReason, UiKind


class AbortFlag:
    """緊急停止の要求。スレッド間で共有する。"""

    def __init__(self) -> None:
        self._event = threading.Event()

    def request(self) -> None:
        self._event.set()

    def is_set(self) -> bool:
        return self._event.is_set()

    def clear(self) -> None:
        self._event.clear()


class SafetyGuard:
    """停止すべきかを判定する。操作の前に必ず通す。"""

    def __init__(self, config: RunnerConfig, flag: AbortFlag) -> None:
        self._config = config
        self._flag = flag

    def abort_requested(self) -> bool:
        return self._flag.is_set()

    def check_ui(self, recognition: Recognition[Any]) -> StopReason | None:
        """画面の種類と信頼度から、操作せずに止めるべきかを返す(WAITING と GAME_OVER は対象外)。"""
        kind = recognition.ui.kind
        if kind is UiKind.FORBIDDEN:
            return StopReason.FORBIDDEN_SCREEN
        if kind is UiKind.UNKNOWN:
            return StopReason.UNKNOWN_SCREEN
        if kind is UiKind.PLAYABLE and (
            recognition.state is None or recognition.confidence < self._config.confidence_threshold
        ):
            return StopReason.LOW_CONFIDENCE
        return None

    def check_progress(
        self,
        *,
        steps_done: int,
        repeated: int,
        unchanged: int,
        waited_sec: float,
    ) -> StopReason | None:
        """進行状況から止めるべきかを返す。

        steps_done: 実行した手の数。repeated: 同じ状態を連続して観測した回数。
        unchanged: 操作しても画面が変わらなかった連続回数。waited_sec: 待機の累計。
        """
        if steps_done >= self._config.step_limit:
            return StopReason.STEP_LIMIT
        if unchanged >= self._config.unchanged_limit:
            return StopReason.NO_SCREEN_CHANGE
        if waited_sec > self._config.wait_limit_sec:
            return StopReason.NO_SCREEN_CHANGE
        if repeated >= self._config.repeated_state_limit:
            return StopReason.REPEATED_STATE
        return None


class _Listener(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...


ListenerFactory = Callable[[Callable[[Any], None]], _Listener]


def _pynput_listener(on_press: Callable[[Any], None]) -> _Listener:
    from pynput import keyboard  # 遅延 import: フックを使う実機でだけ必要

    return keyboard.Listener(on_press=on_press)  # type: ignore[no-any-return]


class KeyboardAbortWatcher:
    """指定キーが押されたら AbortFlag を立てる。別スレッドで動く。"""

    def __init__(
        self,
        flag: AbortFlag,
        key_name: str,
        listener_factory: ListenerFactory = _pynput_listener,
    ) -> None:
        self._flag = flag
        self._key_name = key_name.lower()
        self._listener = listener_factory(self._on_press)

    def start(self) -> None:
        self._listener.start()

    def stop(self) -> None:
        self._listener.stop()

    def _on_press(self, key: Any) -> None:
        # 特殊キーは .name(例: "f12")、文字キーは .char
        name = getattr(key, "name", None) or getattr(key, "char", None)
        if isinstance(name, str) and name.lower() == self._key_name:
            self._flag.request()
