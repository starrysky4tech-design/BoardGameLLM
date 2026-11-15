"""Nature の Phase 0 用: 種のボードの検出の試作(色の連結成分で珠を探し、緑の珠 + 右の珠の組をボードとする)。

使い方: uv run python -m scripts.nature.probe_boards 13_game=1 47_feed_r2=3 ...
引数は「画像名=期待するボードの数」。結果は .steering/20261112-phase-nature/RESULT.md §7。
"""

import sys
from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray

Blob = tuple[float, float, float]  # 中心の x, y と半径
Board = tuple[int, int, int, str, int]  # 緑の珠の x, y, 半径、右の珠の色、右の珠までの距離

D = Path("datasets/raw/nature/feasibility")
K = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))


OPEN_K = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (17, 17))


def blobs(mask: NDArray[np.uint8]) -> list[Blob]:
    closed = np.asarray(cv2.morphologyEx(mask, cv2.MORPH_CLOSE, K), dtype=np.uint8)
    cs, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    filled = np.zeros_like(closed)
    cv2.drawContours(filled, cs, -1, 255, -1)  # 数字の穴を埋める
    # 珠に接した小さい点(満腹の印)を切り離す
    opened = np.asarray(cv2.morphologyEx(filled, cv2.MORPH_OPEN, OPEN_K), dtype=np.uint8)
    n, _, stats, cent = cv2.connectedComponentsWithStats(opened, connectivity=8)
    out: list[Blob] = []
    for i in range(1, n):
        x, y, w, h, a = stats[i]
        if not (30 <= w <= 150 and 30 <= h <= 150):
            continue
        if not (0.75 < w / h < 1.33) or a / (w * h) < 0.55:
            continue
        out.append((float(cent[i][0]), float(cent[i][1]), (w + h) / 4))
    return out


def boards(img: NDArray[np.uint8]) -> list[Board]:
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    green = ((h >= 60) & (h <= 76) & (s > 130) & (v > 110)).astype(np.uint8) * 255
    right = {
        "blue": ((h >= 94) & (h <= 110) & (s > 140) & (v > 120)).astype(np.uint8) * 255,
        "red": (((h <= 7) | (h >= 173)) & (s > 150) & (v > 110)).astype(np.uint8) * 255,
        "grey": ((s < 45) & (v > 150)).astype(np.uint8) * 255,
    }
    right["mixed"] = np.asarray(
        cv2.bitwise_or(right["blue"], right["red"]), dtype=np.uint8
    )  # ハンターの面(赤と青のまだら)
    rb = [(x, y, r, c) for c, m in right.items() for x, y, r in blobs(m)]
    out: list[Board] = []
    for x, y, r in blobs(green):
        for x2, y2, r2, c in rb:
            if 4.3 * r < x2 - x < 7.8 * r and abs(y2 - y) < 0.6 * r and 0.7 < r2 / r < 1.45:
                out.append((round(x), round(y), round(r), c, round(x2 - x)))
    best: dict[tuple[int, int], Board] = {}
    for b in out:  # 同じ緑の珠に複数の色が合ったら、単色を優先する
        key = (b[0], b[1])
        if key not in best or best[key][3] == "mixed":
            best[key] = b
    return sorted(best.values(), key=lambda b: (b[1], b[0]))


def main() -> None:
    expect = dict(a.split("=") for a in sys.argv[1:])
    ok = 0
    for name, n in expect.items():
        image = cv2.imread(str(D / f"{name}.png"))
        if image is None:
            raise SystemExit(f"画像を読めない: {name}")
        found = boards(np.asarray(image, dtype=np.uint8))
        good = len(found) == int(n)
        ok += good
        print("OK " if good else "NG ", name, "expect", n, "found", len(found), found)
    print(f"{ok}/{len(expect)}")


if __name__ == "__main__":
    main()
