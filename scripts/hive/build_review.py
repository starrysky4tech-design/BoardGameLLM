"""記録画面の読み取り結果を、正解ラベルの下書きと確認用の重ね描きにする(Hive の評価セット、手順 b)。

読み取りの結果をそのまま正解にすると、正答率が100%になり確認にならない。そのため、下書きには
reviewed=false を付けて出す。人が重ね描きを見て、json の tops と screen を直し、reviewed を true にする。

使い方:
    uv run python -m scripts.hive.build_review datasets/raw/hive/feasibility datasets/eval/hive
出力:
    <out>/<name>.json         下書き(座標は盤の最小の q, r が 0 になる形)
    <out>/review/<name>.png   マスに「q,r 種類」を重ね描き
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray

from bglm.plugins.hive.logic.models import HexCoord, Piece
from bglm.plugins.hive.vision.grid import Tile, find_tiles, to_axial
from bglm.plugins.hive.vision.recognizer import read_board
from bglm.plugins.hive.vision.screens import screen_of

KIND_LETTER = {"queen": "Q", "ant": "A", "beetle": "B", "grasshopper": "G", "spider": "S"}


def _shift(tops: dict[HexCoord, Piece]) -> dict[HexCoord, Piece]:
    if not tops:
        return {}
    min_q = min(at.q for at in tops)
    min_r = min(at.r for at in tops)
    return {HexCoord(at.q - min_q, at.r - min_r): p for at, p in tops.items()}


def _draw(
    image: NDArray[np.uint8], placed: dict[HexCoord, Tile], tops: dict[HexCoord, Piece]
) -> NDArray[np.uint8]:
    """マスの中心に印を付け、読んだ種類を書く(tops は画面の座標のまま)。"""
    out = image.copy()
    for at, tile in placed.items():
        x, y = int(tile.x), int(tile.y)
        cv2.circle(out, (x, y), 6, (0, 0, 255), -1)
        piece = tops.get(at)
        label = f"{at.q},{at.r}" + (
            f" {piece.color.name[0]}{KIND_LETTER[piece.kind.value]}" if piece else " ?"
        )
        cv2.putText(out, label, (x - 60, y + 85), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("src", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    (args.out / "review").mkdir(parents=True, exist_ok=True)
    for path in sorted(args.src.glob("*.png")):
        loaded = cv2.imread(str(path))
        if loaded is None:
            continue
        image: NDArray[np.uint8] = loaded.astype(np.uint8)
        reading = read_board(image)
        screen = screen_of(bool(reading.tops), reading.problems)
        placed = to_axial(find_tiles(image)) or {}
        shifted = _shift(reading.tops)
        label = {
            "file": path.name,
            "screen": screen.value,
            "reviewed": False,
            "problems": list(reading.problems),
            "tops": [
                {"q": at.q, "r": at.r, "color": p.color.name, "kind": p.kind.value}
                for at, p in sorted(shifted.items(), key=lambda t: (t[0].r, t[0].q))
            ],
        }
        target = args.out / f"{path.stem}.json"
        if target.exists() and json.loads(target.read_text(encoding="utf-8")).get("reviewed"):
            print(f"{path.name}: 確認済みのため上書きしない")
            continue
        target.write_text(json.dumps(label, ensure_ascii=False, indent=2), encoding="utf-8")
        cv2.imwrite(
            str(args.out / "review" / f"{path.stem}.png"), _draw(image, placed, reading.tops)
        )
        print(
            f"{path.name}: {screen.value} tops={len(reading.tops)} problems={list(reading.problems)}"
        )


if __name__ == "__main__":
    main()
