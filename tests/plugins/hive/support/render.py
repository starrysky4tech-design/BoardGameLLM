"""盤面を画面の画像として描く(テスト用)。色は SHG11 の実画面で測った値に合わせる。

マスの中心は grid.pixel_of と同じ式で置く。読み取りの往復(描く → 読む)が元の盤面に戻るかを見るため。
"""

from collections.abc import Mapping

import cv2
import numpy as np
from numpy.typing import NDArray

from bglm.plugins.hive.logic.models import Color, HexCoord, Kind, Piece
from bglm.plugins.hive.vision.grid import TILE_R, pixel_of
from bglm.plugins.hive.vision.pieces import REFERENCE

IMAGE_SIZE = (1080, 2432)  # 幅、高さ
WOOD_BGR = (120, 160, 200)
CREAM_BGR = (225, 235, 240)  # 白系の地(彩度が低く明るい)
BLACK_BGR = (0, 0, 0)  # 黒系の地
OUTLINE_BGR = (70, 70, 70)
SATURATION = {
    Kind.QUEEN: 235,
    Kind.SPIDER: 233,
    Kind.ANT: 206,
    Kind.GRASSHOPPER: 192,
    Kind.BEETLE: 128,
}


def _glyph_bgr(kind: Kind) -> tuple[int, int, int]:
    hue, value = REFERENCE[kind]
    hsv = np.uint8([[[int(hue), SATURATION[kind], int(value)]]])
    bgr = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)[0, 0]
    return int(bgr[0]), int(bgr[1]), int(bgr[2])


def render(
    tops: Mapping[HexCoord, Piece], origin: tuple[float, float] = (540.0, 1200.0)
) -> NDArray[np.uint8]:
    image = np.full((IMAGE_SIZE[1], IMAGE_SIZE[0], 3), WOOD_BGR, np.uint8)
    for at, piece in tops.items():
        cx, cy = pixel_of(at, origin)
        pts = np.array(
            [
                [cx + TILE_R * np.cos(np.deg2rad(60 * k)), cy + TILE_R * np.sin(np.deg2rad(60 * k))]
                for k in range(6)
            ],
            np.int32,
        )
        fill = CREAM_BGR if piece.color is Color.WHITE else BLACK_BGR
        cv2.fillPoly(image, [pts], fill)
        cv2.polylines(image, [pts], True, OUTLINE_BGR, 4)  # 実画面の、マスどうしを隔てる輪郭
        cv2.circle(image, (int(cx), int(cy)), 40, _glyph_bgr(piece.kind), -1)
    return image
