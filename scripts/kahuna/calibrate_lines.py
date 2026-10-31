"""記録した全フレームの杖コマの位置から、点線の位置を補正する(Phase 5)。

各フレームで杖コマを検出し、最も近い点線に割り当て、点線ごとの中心(中央値)を求める。
board.json の概算の9本を、実測で置き換える。出力: datasets/raw/kahuna/work/line_calibration.json と重ね描き。
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

from bglm.plugins.kahuna.logic.models import default_board
from bglm.plugins.kahuna.vision.sticks import MAX_DISTANCE, find_blobs

SESSION = Path("datasets/raw/kahuna/session1")


def load(path: Path) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None
    return np.asarray(image)


def main() -> int:
    board = default_board()
    centers: dict[int, list[tuple[int, int]]] = defaultdict(list)
    far: list[tuple[int, int]] = []
    for path in sorted(SESSION.glob("f*.png")):
        for blob in find_blobs(load(path)):
            d = [
                np.hypot(blob.center.x - ln.position.x, blob.center.y - ln.position.y)
                for ln in board.lines
            ]
            line = int(np.argmin(d))
            if d[line] <= MAX_DISTANCE:
                centers[line].append((blob.center.x, blob.center.y))
            else:
                far.append((blob.center.x, blob.center.y))
    result: dict[str, dict[str, int] | None] = {}
    for line, ln in enumerate(board.lines):
        name = f"{board.islands[ln.a]}-{board.islands[ln.b]}"
        points = np.array(centers.get(line, []))
        if len(points) == 0:
            result[name] = None
            print(f"{name:10s} 検出なし(現在の位置 {ln.position.x},{ln.position.y})")
            continue
        median = np.median(points, axis=0).astype(int)
        spread = float(np.median(np.hypot(*(points - median).T)))
        shift = float(np.hypot(median[0] - ln.position.x, median[1] - ln.position.y))
        result[name] = {"x": int(median[0]), "y": int(median[1]), "n": len(points)}
        print(
            f"{name:10s} 検出{len(points):3d}回 中央値 ({median[0]},{median[1]}) 現在との差 {shift:5.1f} ばらつき {spread:4.1f}"
        )
    print(f"近い点線が無かった検出: {len(far)}件", sorted(set(far))[:8])
    Path("datasets/raw/kahuna/work/line_calibration.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
