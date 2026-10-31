"""CLI の部品の組み立て。実機・ファイル・コンソールとの接続は、ここで一括して行う。

`execute_run` は取得元と入力先を引数で受け取るので、偽の端末でもテストできる。
"""

import time
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from bglm.application.game_io import DryRunDriver, LiveGameIo
from bglm.application.runner import AgentRunner, Mode
from bglm.application.safety import AbortFlag, KeyboardAbortWatcher, SafetyGuard
from bglm.core.config import AndroidTarget, GameConfig, load_game_config
from bglm.core.errors import ConfigError
from bglm.core.models import Frame, RunSummary, StepRecord
from bglm.core.protocols import GamePlugin, InputDriver, RunSink, ScreenSource
from bglm.infrastructure.adb_device import AdbDevice
from bglm.infrastructure.change_detector import PixelRatioDetector
from bglm.infrastructure.run_logger import RunLogger, prune_runs

CONFIG_DIR = Path("config")
RUNS_DIR = Path("runs")
EVAL_DIR = Path("datasets/eval")
GIB = 1024**3


def load_config(game: str, path: Path | None = None) -> GameConfig:
    config = load_game_config(path or CONFIG_DIR / f"{game}.toml")
    if config.game != game:
        raise ConfigError(f"設定のゲーム名が違う: 指定={game!r} 設定={config.game!r}")
    return config


def make_device(config: GameConfig) -> AdbDevice:
    """設定の接続先から端末を作り、接続中であることを確かめる。"""
    target = config.target
    if not isinstance(target, AndroidTarget):
        raise ConfigError(f"接続先 {target.kind!r} は未対応(Phase 1 は android のみ)")
    device = AdbDevice(target)
    device.verify()
    return device


def new_run_id(game: str, now: datetime) -> str:
    return f"{now:%Y%m%d-%H%M%S}-{game}"


def step_line(record: StepRecord) -> str:
    """実行中の1行表示: 手番 / 画面名 / 信頼度 / 選択手 / 所要時間(docs/02「CLI設計」)。"""
    ui = record.recognition["ui"]
    move = record.chosen_move
    move_text = "-" if move is None else str(move.get("type", move))
    seconds = sum(record.elapsed_ms.values()) / 1000
    return (
        f"{record.step:>4}  {ui['screen']:<14} 信頼度 {record.recognition['confidence']:.2f}  "
        f"{move_text:<12} {seconds:5.1f}秒"
    )


class ConsoleSink:
    """RunSink を包み、手を保存するたびに1行を表示する。"""

    def __init__(self, inner: RunSink, echo: Callable[[str], None]) -> None:
        self._inner = inner
        self._echo = echo

    def start(self) -> None:
        self._inner.start()

    def save_frames(
        self, step: int, frames: Sequence[Frame], overlay: NDArray[np.uint8] | None = None
    ) -> list[str]:
        return self._inner.save_frames(step, frames, overlay)

    def save_step(self, record: StepRecord) -> None:
        self._inner.save_step(record)
        self._echo(step_line(record))

    def save_summary(self, summary: RunSummary) -> None:
        self._inner.save_summary(summary)


def execute_run(
    *,
    plugin: GamePlugin[Any, Any],
    config: GameConfig,
    mode: Mode,
    dry_run: bool,
    source: ScreenSource,
    driver: InputDriver,
    runs_root: Path,
    confirm: Callable[[Any], bool] | None,
    echo: Callable[[str], None],
    watch_keyboard: bool = True,
    now: Callable[[], datetime] = datetime.now,
    sleep: Callable[[float], None] = time.sleep,
) -> RunSummary:
    """1回の実行。dry_run のときは、入力をどこにも送らずにループを回す。"""
    flag = AbortFlag()
    guard = SafetyGuard(config.runner, flag)
    io = LiveGameIo(source, DryRunDriver() if dry_run else driver, flag.is_set)
    run_id = new_run_id(config.game, now())
    logger = RunLogger(runs_root, run_id)
    runner = AgentRunner(
        plugin=plugin,
        io=io,
        detector=PixelRatioDetector(),
        sink=ConsoleSink(logger, echo),
        guard=guard,
        config=config.runner,
        run_id=run_id,
        mode=mode,
        confirm=confirm,
        now=now,
        sleep=sleep,
    )
    watcher = KeyboardAbortWatcher(flag, config.runner.abort_key) if watch_keyboard else None
    if watcher is not None:
        watcher.start()
        echo(f"緊急停止キー: {config.runner.abort_key.upper()}")
    try:
        summary = runner.run()
    finally:
        if watcher is not None:
            watcher.stop()
    prune_runs(runs_root, int(config.runner.log_limit_gib * GIB), protect=frozenset({run_id}))
    return summary


def describe_stop(summary: RunSummary, runs_root: Path) -> list[str]:
    """停止時の表示: StopReason、対象の画像パス、再現用のコマンド(docs/02「CLI設計」)。"""
    from bglm.infrastructure.run_logger import load_steps

    lines = [
        f"停止: {summary.stop_reason.value}(手数 {summary.steps}、結果 {summary.result or '-'})"
    ]
    steps = load_steps(runs_root / summary.run_id)
    if steps:
        last = steps[-1]
        if last.frame_paths:
            lines.append(f"画像: {runs_root / summary.run_id / last.frame_paths[0]}")
        lines.append(f"再現: bglm replay {summary.run_id} --step {last.step}")
    return lines
