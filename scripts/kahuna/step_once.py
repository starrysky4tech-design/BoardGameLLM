"""実機で1手だけ、認識 → 思考 → 操作を行う(Phase 7)。

既定は選んだ手を表示するだけ。--execute を付けたときだけ、その手を実機で実行する。
手札を使い切った手番は、画面から手番を区別できないので、引く操作が残っている印
(runs/kahuna/pending_draw)を置く。その印があるときだけ、相手の手番の表示でも盤面を読む。
使い方:
    uv run python -m scripts.kahuna.step_once            # 表示のみ
    uv run python -m scripts.kahuna.step_once --execute  # 表示のあと実行
"""

import argparse
from pathlib import Path

from bglm.application.game_io import LiveGameIo
from bglm.application.safety import AbortFlag
from bglm.cli import wiring
from bglm.core.models import Recognition, TimeBudget
from bglm.plugins.kahuna import create_plugin
from bglm.plugins.kahuna.logic.models import KahunaState, PlaceStick
from bglm.plugins.kahuna.vision.recognizer import KahunaRecognizer

PENDING = Path("runs/kahuna/pending_draw")


def _read(recognizer: KahunaRecognizer, image) -> Recognition[KahunaState]:  # type: ignore[no-untyped-def]
    rec = recognizer.recognize(image)
    if rec.state is None and PENDING.exists() and rec.ui.screen == "opponent_turn":
        return recognizer.read_board_as_my_turn(image)
    return rec


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    config = wiring.load_config("kahuna")
    device = wiring.make_device(config)
    plugin = create_plugin()
    flag = AbortFlag()
    io = LiveGameIo(device, device, flag.is_set)
    recognizer = KahunaRecognizer()

    recognition = _read(recognizer, io.capture().image)
    print(
        f"画面: {recognition.ui.screen} 信頼度 {recognition.confidence:.2f} 読めない {list(recognition.low_confidence)}"
    )
    if recognition.state is None:
        print("盤面を読めないので、操作しない")
        return 1
    legal = plugin.rules().legal_moves(recognition.state)
    move = plugin.strategy().choose(
        recognition.state, legal, TimeBudget(config.runner.think_budget_sec)
    )
    print(f"合法手 {len(legal)}、選んだ手: {move}")
    if not args.execute:
        return 0
    result = plugin.executor().execute(io, recognition.state, move)
    print(f"実行: 成功={result.success} 理由={result.reason}")
    if not result.success:
        return 1
    PENDING.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(move, PlaceStick) and len(recognition.state.hand) == 1:
        PENDING.write_text("hand-empty", encoding="utf-8")  # 最後の1枚を使った。引くまでが手番
    elif PENDING.exists():
        PENDING.unlink()  # 引く操作を終えた
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
