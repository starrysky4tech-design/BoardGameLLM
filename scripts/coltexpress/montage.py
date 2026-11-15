"""Colt Express の Phase 0 用: 保存済みの画面を切り出して縦に並べ、確認用の1枚にする。

使い方: uv run python -m scripts.coltexpress.montage x0,y0,x1,y1 NAME [NAME ...] [--scale 0.5]
"""

import argparse
from pathlib import Path

import cv2
import numpy as np

OUT = Path("datasets/raw/coltexpress/feasibility")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("crop")
    parser.add_argument("names", nargs="+")
    parser.add_argument("--scale", type=float, default=0.5)
    args = parser.parse_args()

    x0, y0, x1, y1 = (int(v) for v in args.crop.split(","))
    parts = []
    for name in args.names:
        image = cv2.imread(str(OUT / f"{name}.png"))
        if image is None:
            raise SystemExit(f"画像を読めなかった: {name}")
        part = image[y0:y1, x0:x1]
        parts.append(
            cv2.resize(part, None, fx=args.scale, fy=args.scale, interpolation=cv2.INTER_AREA)
        )
    cv2.imwrite(str(OUT / "_view.png"), np.vstack(parts))


if __name__ == "__main__":
    main()
