"""全体盤(通常の盤の画面)の幾何: 盤を真上から見た座標への射影変換と、マスごとの領域。座標は原寸(2432x1080)。

カメラは固定なので、盤の 4 隅の画素は、どの対局・どの卓の背景でも同じ(2026-11-10、背景が違う 3 枚で確認)。
4 隅から射影変換を作り、盤を正方形に直した画像(`warp`)の上で、マスごとの領域を、等間隔の格子として計算する。
格子の位置は、直した画像の上で目視して決めた値(`BOARD_MIN`、`BOARD_MAX`、`CORNER`)。

直した画像は、盤の外側に `MARGIN` の余白を持つ。所有の棒(青 = 自分、黄 = AI)は、盤の外側の縁に沿って並ぶ。
"""

from dataclasses import dataclass

import cv2
import numpy as np
from numpy.typing import NDArray

# 盤の 4 隅の画素(原寸)。左上、右上、右下、左下。実機の画像(表示座標 1.22 倍)の目測
SRC_CORNERS = np.array(
    [
        [748 * 1.22, 183 * 1.22],
        [1312 * 1.22, 183 * 1.22],
        [1405 * 1.22, 712 * 1.22],
        [655 * 1.22, 712 * 1.22],
    ],
    dtype=np.float32,
)
SIDE = 1100  # 直した画像の、盤の一辺(画素)
MARGIN = 160  # 盤の外側の余白(棒を含める)
CANVAS = SIDE + 2 * MARGIN

# 直した画像(余白つき)の座標で、格子の位置。角のマスを除く辺のマスが、等間隔(PITCH)で 9 個並ぶ
INNER_MIN = 312  # 左の列の右端 = 上の行の下端 の座標(内側の縁)
INNER_MAX = 1097  # 右の列の左端 = 下の行の上端
OUTER_MIN = 172  # 盤の外枠(マスの外側の縁)
OUTER_MAX = 1240
PITCH = (INNER_MAX - INNER_MIN) / 9
BAND = 32  # 色の帯の厚さ(マスの内側の縁から)
BAR_GAP = 4  # マスの外側の縁から、棒の領域までの隙間
BAR_THICK = 44  # 棒の領域の厚さ(棒は約 25 画素)


@dataclass(frozen=True)
class Rect:
    x0: int
    y0: int
    x1: int
    y1: int

    def crop(self, image: NDArray[np.uint8]) -> NDArray[np.uint8]:
        return image[self.y0 : self.y1, self.x0 : self.x1]

    @property
    def area(self) -> int:
        return (self.x1 - self.x0) * (self.y1 - self.y0)


@dataclass(frozen=True)
class TileRegions:
    position: int
    tile: Rect  # マス全体
    band: Rect  # 色の帯(家が並ぶ。街だけ意味がある)
    body: Rect  # 帯を除いた、マスの本体(抵当の印が出る)
    bar: Rect  # 所有の棒の領域(盤の外側)


def homography() -> NDArray[np.float64]:
    """原寸の画像 → 直した画像(余白つき)の射影変換。"""
    dst = np.array(
        [
            [MARGIN, MARGIN],
            [MARGIN + SIDE, MARGIN],
            [MARGIN + SIDE, MARGIN + SIDE],
            [MARGIN, MARGIN + SIDE],
        ],
        dtype=np.float32,
    )
    return np.asarray(
        cv2.getPerspectiveTransform(SRC_CORNERS, dst),
        dtype=np.float64,
    )


def warp(image: NDArray[np.uint8]) -> NDArray[np.uint8]:
    """盤を真上から見た画像にする(CANVAS 四方)。"""
    return np.asarray(cv2.warpPerspective(image, homography(), (CANVAS, CANVAS)), dtype=np.uint8)


def _span(index: int) -> tuple[int, int]:
    """辺のマス(index = 1〜9)の、辺に沿った範囲。格子は、内側の縁から数える。"""
    lo = INNER_MIN + (index - 1) * PITCH
    return round(lo), round(lo + PITCH)


def tile_regions(position: int) -> TileRegions:
    """位置(0〜39)のマスの領域。角(0、10、20、30)は、辺のマスと違う大きさで、このプロジェクトでは使わない。"""
    if position % 10 == 0:
        raise ValueError(f"角のマスは扱わない: {position}")
    side, index = divmod(position, 10)
    lo, hi = _span(index if side in (2, 3) else 10 - index)
    o_min, o_max, i_min, i_max = OUTER_MIN, OUTER_MAX, INNER_MIN, INNER_MAX
    m = 0  # 格子の定数は、余白を含む座標で測った値
    if side == 0:  # 下の行。GO(右下)から左へ
        tile = Rect(lo + m, i_max + m, hi + m, o_max + m)
        band = Rect(tile.x0, tile.y0, tile.x1, tile.y0 + BAND)
        body = Rect(tile.x0, band.y1, tile.x1, tile.y1)
        bar = Rect(tile.x0, tile.y1 + BAR_GAP, tile.x1, tile.y1 + BAR_GAP + BAR_THICK)
    elif side == 1:  # 左の列。下(Jail の隣)から上へ
        tile = Rect(o_min + m, lo + m, i_min + m, hi + m)
        band = Rect(tile.x1 - BAND, tile.y0, tile.x1, tile.y1)
        body = Rect(tile.x0, tile.y0, band.x0, tile.y1)
        bar = Rect(tile.x0 - BAR_GAP - BAR_THICK, tile.y0, tile.x0 - BAR_GAP, tile.y1)
    elif side == 2:  # 上の行。左(Free Parking の隣)から右へ
        tile = Rect(lo + m, o_min + m, hi + m, i_min + m)
        band = Rect(tile.x0, tile.y1 - BAND, tile.x1, tile.y1)
        body = Rect(tile.x0, tile.y0, tile.x1, band.y0)
        bar = Rect(tile.x0, tile.y0 - BAR_GAP - BAR_THICK, tile.x1, tile.y0 - BAR_GAP)
    else:  # 右の列。上(Go To Jail の隣)から下へ
        tile = Rect(i_max + m, lo + m, o_max + m, hi + m)
        band = Rect(tile.x0, tile.y0, tile.x0 + BAND, tile.y1)
        body = Rect(band.x1, tile.y0, tile.x1, tile.y1)
        bar = Rect(tile.x1 + BAR_GAP, tile.y0, tile.x1 + BAR_GAP + BAR_THICK, tile.y1)
    return TileRegions(position, tile, band, body, bar)
