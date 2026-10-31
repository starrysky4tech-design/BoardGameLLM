"""場札と手札の読み取りを、記録したフレームで試す(開発用)。"""

import sys
import time
from pathlib import Path

import cv2
import numpy as np

from bglm.plugins.kahuna.logic.models import default_board
from bglm.plugins.kahuna.vision.cards import read_hand, read_market
from bglm.plugins.kahuna.vision.templates import TemplateSet

SESSION = Path("datasets/raw/kahuna/session1")


def load(path: Path) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None
    return np.asarray(image)


def main() -> int:
    board = default_board()
    templates = TemplateSet.load()
    files = sorted(SESSION.glob("f*.png"))
    indices = [int(a) for a in sys.argv[1:]] or [12, 18, 39, 66, 126, 129, 150]
    for i in indices:
        image = load(files[i])
        started = time.perf_counter()
        market, market_conf = read_market(image, templates)
        hand = read_hand(image, templates)
        elapsed = time.perf_counter() - started
        m = [board.islands[r.island] if r else "-" for r in market]
        h = [f"{board.islands[c.island]}({c.score:.2f})@{c.x},{c.y}" for c in hand]
        print(f"[{i:3d}] {elapsed * 1000:4.0f}ms 場札 {m} 信頼度{market_conf:.2f}\n      手札 {h}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
