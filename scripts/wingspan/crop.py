"""保存した画面の一部を切り出して確認用に保存する(札の表を作るときに、印を目で確かめる道具)。

使い方: uv run python -m scripts.wingspan.crop NAME X0 Y0 X1 Y1 [--scale 1.0] [--out NAME]
座標は原寸(2432x1080)。NAME は datasets/raw/wingspan/feasibility/ の画像名(拡張子なし)。
複数の切り出しを横に並べるときは、`--also NAME2 X0 Y0 X1 Y1` を繰り返す(高さは最初のものに揃える)。
"""

import argparse
from pathlib import Path

import cv2
import numpy as np

SRC = Path("datasets/raw/wingspan/feasibility")
OUT = SRC / "_crop.png"


def load(name: str, box: tuple[int, int, int, int]) -> np.ndarray:
    image = cv2.imread(str(SRC / f"{name}.png"))
    if image is None:
        raise SystemExit(f"画像を読めない: {name}")
    x0, y0, x1, y1 = box
    return np.asarray(image[y0:y1, x0:x1])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("name")
    parser.add_argument("box", nargs=4, type=int)
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument(
        "--also", nargs=5, action="append", default=[], metavar=("NAME", "X0", "Y0", "X1", "Y1")
    )
    args = parser.parse_args()

    parts = [load(args.name, (args.box[0], args.box[1], args.box[2], args.box[3]))]
    for entry in args.also:
        box = (int(entry[1]), int(entry[2]), int(entry[3]), int(entry[4]))
        parts.append(load(entry[0], box))
    height = parts[0].shape[0]
    resized = [
        cv2.resize(p, (max(1, round(p.shape[1] * height / p.shape[0])), height)) for p in parts
    ]
    merged = np.hstack(resized)
    if args.scale != 1.0:
        merged = cv2.resize(
            merged, None, fx=args.scale, fy=args.scale, interpolation=cv2.INTER_AREA
        )
    cv2.imwrite(str(OUT), merged)
    print(OUT, merged.shape[1], merged.shape[0])


if __name__ == "__main__":
    main()
