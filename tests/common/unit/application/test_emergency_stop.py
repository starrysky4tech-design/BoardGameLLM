"""緊急停止キー押下から1秒以内に入力が止まること(docs/01 の非機能要件「信頼性」)。

実際のスレッドと時計で、実行ループ・LiveGameIo・キー監視をつなげて確かめる。
"""

import threading
import time
from datetime import datetime
from typing import Any

import numpy as np
from tests.common.support.fake_game import ArrayEqualDetector, FakePlugin, MemorySink, playable

from bglm.application.game_io import LiveGameIo
from bglm.application.runner import AgentRunner
from bglm.application.safety import AbortFlag, KeyboardAbortWatcher, SafetyGuard
from bglm.core.config import RunnerConfig
from bglm.core.models import Frame, InputAction, StopReason

TAP_INTERVAL_SEC = 0.05


class FakeSource:
    def capture(self) -> Frame:
        image = np.full((8, 8, 3), 10, dtype=np.uint8)
        return Frame.from_image(image, datetime(2026, 10, 30))


class TimestampedDriver:
    def __init__(self) -> None:
        self.sent_at: list[float] = []

    def perform(self, action: InputAction) -> None:
        self.sent_at.append(time.monotonic())


class FakeKey:
    name = "f12"
    char = None


def test_input_stops_within_one_second_of_the_abort_key() -> None:
    flag = AbortFlag()
    driver = TimestampedDriver()
    io = LiveGameIo(FakeSource(), driver, flag.is_set)
    plugin = FakePlugin([playable(0)], taps=20)  # 1手が1秒かかる長い操作
    plugin.executor().hook = lambda i: time.sleep(TAP_INTERVAL_SEC)
    config = RunnerConfig()
    runner: AgentRunner[int, Any] = AgentRunner(
        plugin=plugin,
        io=io,
        detector=ArrayEqualDetector(),
        sink=MemorySink(),
        guard=SafetyGuard(config, flag),
        config=config,
        run_id="r",
        mode="auto",
    )

    on_press: list[Any] = []
    watcher = KeyboardAbortWatcher(
        flag, config.abort_key, lambda cb: on_press.append(cb) or _NoopListener()
    )
    watcher.start()
    pressed_at: list[float] = []

    def press_f12_midway() -> None:
        time.sleep(0.12)
        pressed_at.append(time.monotonic())
        on_press[0](FakeKey())

    presser = threading.Thread(target=press_f12_midway)
    presser.start()
    summary = runner.run()
    finished_at = time.monotonic()
    presser.join()

    assert summary.stop_reason is StopReason.USER_ABORT
    assert finished_at - pressed_at[0] < 1.0
    assert 1 <= len(driver.sent_at) < 20  # 操作の途中で止まった(最初の数回は送られている)
    late = [t for t in driver.sent_at if t > pressed_at[0] + TAP_INTERVAL_SEC]
    assert late == [], "キー押下の後に入力が送られた"


class _NoopListener:
    def start(self) -> None: ...

    def stop(self) -> None: ...
