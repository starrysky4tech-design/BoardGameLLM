"""認識結果を重ね描きして、人が確かめるためのシートを作る(Phase 5)。

使い方: uv run python -m scripts.kahuna.review_frames <出力名> <フレーム番号>...
出力: datasets/raw/kahuna/work/review_<出力名>.png(1枚に4フレーム。盤の全体に、認識した杖コマ・石・手札・場札・数値を重ねる)
"""

import sys
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from bglm.core.models import Frame
from bglm.plugins.kahuna.logic.models import default_board
from bglm.plugins.kahuna.vision.recognizer import KahunaRecognizer

SESSION = Path("datasets/raw/kahuna/session1")


def main() -> int:
    name, indices = sys.argv[1], [int(a) for a in sys.argv[2:]]
    files = sorted(SESSION.glob("f*.png"))
    recognizer, board = KahunaRecognizer(), default_board()
    tiles = []
    for i in indices:
        image = np.asarray(
            cv2.imdecode(np.fromfile(files[i], dtype=np.uint8), cv2.IMREAD_COLOR), dtype=np.uint8
        )
        rec = recognizer.recognize(image)
        view = recognizer.debug_overlay(Frame.from_image(image, datetime.now()), rec)
        s = rec.state
        if s is not None:
            hand = [board.islands[c] for c in s.hand]
            market = [board.islands[c] for c in s.market]
            text = f"#{i} hand={hand} mkt={market} deck={s.deck_count} r={s.round} sc={s.scores}"
        else:
            text = f"#{i} {rec.ui.screen} low={rec.low_confidence}"
        cv2.rectangle(view, (0, 130), (2432, 175), (0, 0, 0), -1)
        cv2.putText(view, text, (70, 165), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 255, 255), 3)
        tiles.append(cv2.resize(view[120:1080, 60:2200], (1100, 480)))
    while len(tiles) % 2:
        tiles.append(np.zeros_like(tiles[0]))
    sheet = np.vstack([np.hstack(tiles[r : r + 2]) for r in range(0, len(tiles), 2)])
    out = Path("datasets/raw/kahuna/work") / f"review_{name}.png"
    cv2.imencode(".png", sheet)[1].tofile(str(out))
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
