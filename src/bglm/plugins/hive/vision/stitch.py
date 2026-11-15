"""盤を左右へ寄せた複数の画面を、1つの格子に継ぎ合わせる(docs/02 の「Hiveの認識」の段階1)。

最初の画面を基準にして、各画面が基準からどれだけずれたか(位相相関)を求める。
ずれた分だけマスの位置を戻し、同じマスは1つにまとめる。盤が画面より広くても、
寄せた画面どうしで重なる部分から、全体を読める。
"""

from dataclasses import replace

import cv2
import numpy as np
from numpy.typing import NDArray

from bglm.plugins.hive.vision.grid import Tile, find_tiles
from bglm.plugins.hive.vision.recognizer import BoardReading, read_tiles

BAND = (400, 2050)  # 盤の縦の範囲(手持ちの列は含めない)。ずれを求める部分
SAME_TILE_PX = 25.0  # この距離より近いマスは、同じマスとみなす


def measure_shift(reference: NDArray[np.uint8], other: NDArray[np.uint8]) -> tuple[float, float]:
    """other の内容が reference からどれだけずれているか(画素)。左へ寄せると負になる。"""
    y0, y1 = BAND
    a = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)[y0:y1].astype(np.float32)
    b = cv2.cvtColor(other, cv2.COLOR_BGR2GRAY)[y0:y1].astype(np.float32)
    (dx, dy), _ = cv2.phaseCorrelate(a, b)
    return float(dx), float(dy)


def stitch_tiles(frames: list[NDArray[np.uint8]]) -> list[Tile]:
    """frames[0] を基準の座標にして、各画面のマスを1つにまとめる。"""
    if not frames:
        return []
    reference = frames[0]
    merged: list[Tile] = []
    for image in frames:
        dx, dy = measure_shift(reference, image)
        for tile in find_tiles(image):
            x, y = tile.x - dx, tile.y - dy  # 内容がずれた分だけ、基準の座標へ戻す
            if any(abs(m.x - x) < SAME_TILE_PX and abs(m.y - y) < SAME_TILE_PX for m in merged):
                continue
            merged.append(replace(tile, x=x, y=y))
    return merged


def read_stitched(frames: list[NDArray[np.uint8]]) -> BoardReading:
    """寄せた画面の組から盤を読む。"""
    return read_tiles(stitch_tiles(frames))
