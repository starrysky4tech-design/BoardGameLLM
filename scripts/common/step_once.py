"""実機で1手だけ、認識 → 思考 → 操作を行う(GamePlugin の形のゲーム。kahuna、hive)。

既定は選んだ手を表示するだけ。--execute を付けたときだけ、その手を実機で実行する。
ゲーム固有の差し込み(認識の仕方、実行の後の処理)は scripts/<game>/step_hooks.py の HOOKS に置く。
使い方:
    uv run python -m scripts.common.step_once --game kahuna            # 表示のみ
    uv run python -m scripts.common.step_once --game kahuna --execute  # 表示のあと実行
    uv run python -m scripts.common.step_once --game hive --from-start # 盤が空の初期状態から読み始める
"""

import argparse
import importlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from bglm.application.game_io import LiveGameIo
from bglm.application.registry import PluginRegistry
from bglm.application.safety import AbortFlag
from bglm.cli.wiring import load_config, make_device
from bglm.core.models import Recognition, TimeBudget
from bglm.core.protocols import GameIo


@dataclass(frozen=True)
class StepHooks:
    """ゲーム固有の差し込み。None のものは既定の動作になる。"""

    # (plugin, io, from_start) → 認識。既定は plugin.recognizer().observe(io, None)
    observe: Callable[[Any, GameIo, bool], Recognition[Any]] | None = None
    # (実行前の状態, 実行した手)。実行が成功した後に呼ぶ
    after: Callable[[Any, Any], None] | None = None


def load_hooks(game: str) -> StepHooks:
    """scripts/<game>/step_hooks.py の HOOKS。ファイルが無ければ既定。"""
    module_name = f"scripts.{game}.step_hooks"
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as e:
        if e.name == module_name:
            return StepHooks()
        raise
    hooks = getattr(module, "HOOKS", None)
    if not isinstance(hooks, StepHooks):
        raise TypeError(f"{module_name} の HOOKS が StepHooks ではない")
    return hooks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="実機で1手だけ、認識 → 思考 → 操作を行う")
    parser.add_argument("--game", required=True, help="ゲーム名(config/<game>.toml)")
    parser.add_argument("--execute", action="store_true", help="選んだ手を実機で実行する")
    parser.add_argument("--from-start", action="store_true", help="対局の初期状態から読み始める")
    args = parser.parse_args(argv)

    hooks = load_hooks(args.game)
    config = load_config(args.game)
    device = make_device(config)
    plugin = PluginRegistry().load(args.game)
    flag = AbortFlag()
    io = LiveGameIo(device, device, flag.is_set)

    if hooks.observe is not None:
        recognition = hooks.observe(plugin, io, args.from_start)
    else:
        recognition = plugin.recognizer().observe(io, None)
    print(
        f"画面: {recognition.ui.screen} 信頼度 {recognition.confidence:.2f} "
        f"読めない {list(recognition.low_confidence)}"
    )
    state = recognition.state
    if state is None:
        print("盤面を読めないので、操作しない")
        return 1
    legal = plugin.rules().legal_moves(state)
    move = plugin.strategy().choose(state, legal, TimeBudget(config.runner.think_budget_sec))
    print(f"合法手 {len(legal)}、選んだ手: {move}")
    if not args.execute:
        return 0
    result = plugin.executor().execute(io, state, move)
    print(f"実行: 成功={result.success} 理由={result.reason}")
    if not result.success:
        return 1
    if hooks.after is not None:
        hooks.after(state, move)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
