"""実行ループのテスト用の偽ゲーム。固定の画面列(スクリプト)を順に返す。

状態は整数、手は Go() だけ。実機にも実際のゲームにも依存しない。
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
from numpy.typing import NDArray

from bglm.application.game_io import ReplayGameIo
from bglm.application.runner import AgentRunner, Mode
from bglm.application.safety import AbortFlag, SafetyGuard
from bglm.core.config import RunnerConfig
from bglm.core.models import (
    ExecutionResult,
    Frame,
    Point,
    Recognition,
    RunSummary,
    StepRecord,
    Tap,
    TimeBudget,
    UiKind,
    UiState,
    VlmProfile,
)
from bglm.core.protocols import GameIo, RunSink

NOW = datetime(2026, 10, 30, 12, 0, 0)


@dataclass(frozen=True)
class Go:
    """偽ゲームの唯一の手。"""


def frame(value: int, size: int = 8) -> Frame:
    return Frame.from_image(np.full((size, size, 3), value, dtype=np.uint8), NOW)


def distinct_frames(n: int) -> list[Frame]:
    """どの2枚も十分に違う画像(画面が変わったと判定される)。値は 10, 60, 110, ... と離す。"""
    return [frame((10 + 50 * i) % 250) for i in range(n)]


def rec(
    kind: UiKind = UiKind.PLAYABLE,
    state: int | None = 0,
    confidence: float = 1.0,
    screen: str = "main",
) -> Recognition[int]:
    return Recognition(UiState(kind, screen), state=state, confidence=confidence)


def playable(state: int, confidence: float = 1.0) -> Recognition[int]:
    return rec(UiKind.PLAYABLE, state, confidence)


class ScriptedRecognizer:
    """observe のたびに画面を1枚取得し、スクリプトの次の認識結果を返す。例外を置けば送出する。"""

    def __init__(self, script: Sequence[Recognition[int] | Exception]) -> None:
        self._script = list(script)
        self.previous_seen: list[int | None] = []
        self.overlays = 0

    def observe(self, io: GameIo, previous: int | None) -> Recognition[int]:
        self.previous_seen.append(previous)
        index = len(self.previous_seen) - 1
        assert index < len(self._script), "スクリプトを使い切った(実行ループが止まらなかった)"
        item = self._script[index]
        if isinstance(item, Exception):
            raise item
        io.capture()
        return item

    def debug_overlay(self, frame: Frame, result: Recognition[int]) -> NDArray[np.uint8]:
        self.overlays += 1
        return frame.image


class FakeRules:
    def __init__(self, no_moves_for: frozenset[int] = frozenset()) -> None:
        self._no_moves_for = no_moves_for

    def legal_moves(self, state: int) -> list[Go]:
        return [] if state in self._no_moves_for else [Go()]

    def apply(self, state: int, move: Go) -> int:
        return state + 1

    def is_terminal(self, state: int) -> bool:
        return False

    def outcome(self, state: int) -> str | None:
        return "win" if state > 0 else "lose"

    def diff(self, predicted: int, actual: int) -> dict[str, Any]:
        return {} if predicted == actual else {"state": [predicted, actual]}


class FakeStrategy:
    def __init__(self) -> None:
        self.budgets: list[TimeBudget] = []
        self.illegal = False

    def choose(self, state: int, legal: Sequence[Go], budget: TimeBudget) -> Go:
        self.budgets.append(budget)

        @dataclass(frozen=True)
        class Other:
            pass

        return Other() if self.illegal else legal[0]  # type: ignore[return-value]


class FakeExecutor:
    """1手につき taps 回タップする。hook は各タップの前に呼ばれる。"""

    def __init__(self, taps: int = 1) -> None:
        self.taps = taps
        self.hook: Callable[[int], None] | None = None
        self.raises: Exception | None = None
        self.fails = False
        self.calls = 0

    def execute(self, io: GameIo, state: int, move: Go) -> ExecutionResult:
        self.calls += 1
        for i in range(self.taps):
            if self.hook is not None:
                self.hook(i)
            io.perform(Tap(Point(self.calls, i)))
        if self.raises is not None:
            raise self.raises
        if self.fails:
            return ExecutionResult(success=False, reason="想定外の画面")
        return ExecutionResult(success=True)


class FakePlugin:
    name = "fake"

    def __init__(
        self,
        script: Sequence[Recognition[int] | Exception],
        no_moves_for: frozenset[int] = frozenset(),
        taps: int = 1,
    ) -> None:
        self._recognizer = ScriptedRecognizer(script)
        self._rules = FakeRules(no_moves_for)
        self._strategy = FakeStrategy()
        self._executor = FakeExecutor(taps)

    def recognizer(self) -> ScriptedRecognizer:
        return self._recognizer

    def rules(self) -> FakeRules:
        return self._rules

    def strategy(self) -> FakeStrategy:
        return self._strategy

    def executor(self) -> FakeExecutor:
        return self._executor

    def vlm_profile(self) -> VlmProfile | None:
        return None


class ArrayEqualDetector:
    """画像が1画素でも違えば「変わった」とする(単体テスト用)。"""

    def changed(self, before: Frame, after: Frame, region: object = None) -> bool:
        return not np.array_equal(before.image, after.image)


@dataclass
class MemorySink:
    started: int = 0
    steps: list[StepRecord] = field(default_factory=list)
    saved_frames: list[tuple[int, int, bool]] = field(
        default_factory=list
    )  # (step, 枚数, overlay有無)
    summaries: list[RunSummary] = field(default_factory=list)

    def start(self) -> None:
        self.started += 1

    def save_frames(
        self, step: int, frames: Sequence[Frame], overlay: NDArray[np.uint8] | None = None
    ) -> list[str]:
        self.saved_frames.append((step, len(frames), overlay is not None))
        return [f"steps/{step:06d}/frame_{i:02d}.png" for i in range(1, len(frames) + 1)]

    def save_step(self, record: StepRecord) -> None:
        self.steps.append(record)

    def save_summary(self, summary: RunSummary) -> None:
        self.summaries.append(summary)

    @property
    def actions_sent(self) -> int:
        return sum(len(s.actions) for s in self.steps)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@dataclass
class Harness:
    runner: AgentRunner[int, Go]
    plugin: FakePlugin
    sink: Any
    io: ReplayGameIo
    flag: AbortFlag
    sleeps: list[float]
    confirmed: list[Go]

    def run(self) -> RunSummary:
        return self.runner.run()


def build(
    script: Sequence[Recognition[int] | Exception],
    *,
    frames: Sequence[Frame] | None = None,
    config: RunnerConfig | None = None,
    mode: Mode = "auto",
    approve: bool = True,
    no_moves_for: frozenset[int] = frozenset(),
    taps: int = 1,
    io: ReplayGameIo | None = None,
    flag: AbortFlag | None = None,
    sink: RunSink | None = None,
) -> Harness:
    plugin = FakePlugin(script, no_moves_for, taps)
    config = config or RunnerConfig()
    flag = flag or AbortFlag()
    io = io or ReplayGameIo(frames if frames is not None else distinct_frames(len(script) + 1))
    sink = sink or MemorySink()
    sleeps: list[float] = []
    confirmed: list[Go] = []

    def confirm(move: Go) -> bool:
        confirmed.append(move)
        return approve

    runner: AgentRunner[int, Go] = AgentRunner(
        plugin=plugin,
        io=io,
        detector=ArrayEqualDetector(),
        sink=sink,
        guard=SafetyGuard(config, flag),
        config=config,
        run_id="run-1",
        mode=mode,
        confirm=confirm if mode == "step" else None,
        clock=FakeClock(),
        now=lambda: NOW,
        sleep=sleeps.append,
    )
    return Harness(runner, plugin, sink, io, flag, sleeps, confirmed)
