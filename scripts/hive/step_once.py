"""実機で Hive の1手だけ、認識 → 思考 → 操作を行う(Kahuna の step_once と同じ流れ)。

既定は選んだ手を表示するだけ。--execute を付けたときだけ、その手を実機で実行する。
認識は直前の状態を必要とする。対局の最初の1手は、初期状態(空の盤)から始めるので --from-start を付ける。
使い方:
    uv run python -m scripts.hive.step_once --from-start            # 表示のみ
    uv run python -m scripts.hive.step_once --from-start --execute  # 表示のあと実行
"""

import argparse

from bglm.application.game_io import LiveGameIo
from bglm.application.safety import AbortFlag
from bglm.cli import wiring
from bglm.core.models import TimeBudget
from bglm.plugins.hive import create_plugin
from bglm.plugins.hive.logic.models import initial_state


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--from-start", action="store_true", help="盤が空の初期状態から読み始める")
    args = parser.parse_args()

    config = wiring.load_config("hive")
    device = wiring.make_device(config)
    plugin = create_plugin()
    flag = AbortFlag()
    io = LiveGameIo(device, device, flag.is_set)
    previous = initial_state() if args.from_start else None

    recognition = plugin.recognizer().observe(io, previous)
    print(
        f"画面: {recognition.ui.screen} 信頼度 {recognition.confidence:.2f} "
        f"読めない {list(recognition.low_confidence)}"
    )
    if recognition.state is None:
        print("盤面を読めないので、操作しない")
        return 1
    rules = plugin.rules()
    legal = rules.legal_moves(recognition.state)
    move = plugin.strategy().choose(
        recognition.state, legal, TimeBudget(config.runner.think_budget_sec)
    )
    print(f"合法手 {len(legal)}、選んだ手: {move}")
    if not args.execute:
        return 0
    result = plugin.executor().execute(io, recognition.state, move)
    print(f"実行: 成功={result.success} 理由={result.reason}")
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
