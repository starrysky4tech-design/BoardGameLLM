"""実機の画面を1枚取得して認識結果を表示する(Phase 7: 対戦中の読み取り専用の確認)。

入力は一切送らない。取得した画像は runs/capture/ に保存する。

使い方:
    uv run python -m scripts.common.observe --wait 20
--wait は取得の前に待つ秒数(相手の手番の終わりを待つため)。
"""

import argparse
import time
from datetime import datetime
from pathlib import Path

from bglm.cli import wiring
from bglm.infrastructure.run_logger import write_png
from bglm.plugins.kahuna.logic.models import default_board
from bglm.plugins.kahuna.vision.alignment import aligned_view
from bglm.plugins.kahuna.vision.describe import describe_recognition
from bglm.plugins.kahuna.vision.recognizer import KahunaRecognizer
from bglm.plugins.kahuna.vision.templates import TemplateSet


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--game", default="kahuna")
    parser.add_argument("--wait", type=float, default=0.0)
    args = parser.parse_args()

    if args.wait > 0:
        time.sleep(args.wait)
    config = wiring.load_config(args.game)
    device = wiring.make_device(config)
    frame = device.capture()
    out = Path("runs/capture") / f"{args.game}-{datetime.now():%Y%m%d-%H%M%S}.png"
    write_png(out, frame.image)

    rec = KahunaRecognizer().recognize(frame.image)
    print(f"{rec.ui.screen} 信頼度 {rec.confidence:.2f} 読めない要素 {list(rec.low_confidence)}")
    print(f"画像: {out}")
    if rec.state is None:
        return 0
    d = describe_recognition(rec)
    for key in ("hand", "market", "deck", "round", "score_me", "score_opponent"):
        print(f"{key}: {d.get(key)}")
    sticks = {k: v for k, v in d.items() if k.startswith("sticks") and v != "-"}
    print(f"杖コマ: {sticks}")
    board = default_board()
    _, alignment = aligned_view(frame.image, TemplateSet.load().anchor) or (None, None)
    if alignment is not None:
        for key in sorted(sticks):
            index = int(key[len("sticks[") : -1])
            p = board.lines[index].position
            print(f"  {key} の押す位置: ({p.x + alignment.dx}, {p.y + alignment.dy})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
