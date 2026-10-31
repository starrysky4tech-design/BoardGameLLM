"""手札の読み取りの結果を、人が確かめるための一覧を作る(Phase 5)。

各フレームの手札の領域に、読み取った島名と位置を書き込み、連番のシートにする。
出力: datasets/raw/kahuna/work/hand_check_N.png(1枚に20フレーム)
"""

import sys
from pathlib import Path

import cv2
import numpy as np

from bglm.plugins.kahuna.logic.models import default_board
from bglm.plugins.kahuna.vision.cards import read_hand
from bglm.plugins.kahuna.vision.templates import TemplateSet

SESSION = Path("datasets/raw/kahuna/session1")
OUT = Path("datasets/raw/kahuna/work")


def load(path: Path) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None
    return np.asarray(image)


def main() -> int:
    first, last = (int(a) for a in sys.argv[1:3]) if len(sys.argv) >= 3 else (10, 170)
    board = default_board()
    templates = TemplateSet.load()
    files = sorted(SESSION.glob("f*.png"))
    tiles = []
    results = {}
    for i in range(first, min(last, len(files))):
        image = load(files[i])
        hand = read_hand(image, templates)
        results[i] = [board.islands[c.island] for c in hand]
        view = image[200:960, 1560:2010].copy()
        for card in hand:
            cx, cy = card.x - 1560, card.y - 200
            cv2.circle(view, (cx, cy), 6, (0, 0, 255), -1)
            cv2.putText(
                view,
                f"{board.islands[card.island][:2]}{card.score:.2f}",
                (cx + 8, cy + 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 255),
                2,
            )
        view = cv2.resize(view, (225, 380))
        cv2.putText(view, str(i), (4, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        tiles.append(view)
    per_sheet = 20
    for s in range(0, len(tiles), per_sheet):
        chunk = tiles[s : s + per_sheet]
        while len(chunk) % 10:
            chunk.append(np.zeros_like(chunk[0]))
        sheet = np.vstack([np.hstack(chunk[r : r + 10]) for r in range(0, len(chunk), 10)])
        cv2.imencode(".png", sheet)[1].tofile(str(OUT / f"hand_check_{s // per_sheet + 1}.png"))
    for i, names in results.items():
        print(i, names)
    return 0


if __name__ == "__main__":
    sys.exit(main())
