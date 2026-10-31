"""盤のマス(平らな上下の六角形)の検出と、画面座標 ↔ 軸座標の変換(docs/02「Recognizer」)。

取得画像 1080x2432 を基準にした寸法。マスは白系(薄い地)と黒系(暗い地)の2種類があり、
地の色が駒の側(白・黒)を表す。駒の種類は地の上の絵の色で決める(pieces.py)。
盤の拡大・移動があれば、マスの間隔(TILE_R)を変えて合わせる。
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

import cv2
import numpy as np
from numpy.typing import NDArray

from bglm.plugins.hive.logic.models import Color, HexCoord

TILE_R = 77.3  # マスの外接円の半径(画素)。実画面で最小二乗から求めた値(幅 2R≈155、高さ √3R≈134)
TILE_H = math.sqrt(3) * TILE_R
BOARD_TOP = 360  # 手持ちの列(上)より下(手持ちの下端は約355)
BOARD_BOTTOM = 2110  # 手持ちの列(下)より上(手持ちの上端は約2135)
TILE_MIN_AREA = 6000
TILE_MAX_AREA = 22000
GLYPH_MIN_SATURATION = 110
GLYPH_MIN_VALUE = 60
CREAM_MAX_SATURATION = 60
CREAM_MIN_VALUE = 170
DARK_MAX_VALUE = 12  # 黒いマスの内側だけを取る(影や輪郭の暗い画素は除く)
FIT_TOLERANCE = (
    5.0  # 最小二乗の格子からのずれの許容(画素)。game 画面は約3.5、別の拡大のチュートリアルは約10
)


@dataclass(frozen=True)
class Tile:
    x: float
    y: float
    side: Color  # 地の色。白系は WHITE、黒系は BLACK
    area: int
    glyph_hsv: NDArray[np.uint8]  # 絵の画素(N×3。OpenCVの HSV)。種類の判定に使う


HAND_TOP = 2100  # 自分の手持ちの列の範囲(下端の列。手持ちの中心は約2185)
HAND_BOTTOM = 2350


def ground_masks(
    image: NDArray[np.uint8], top: int = BOARD_TOP, bottom: int = BOARD_BOTTOM
) -> tuple[NDArray[np.uint8], NDArray[np.uint8]]:
    """白系の地と黒系の地の2つの2値画像(盤の範囲だけ)。"""
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    sat, val = hsv[:, :, 1], hsv[:, :, 2]
    cream = ((sat < CREAM_MAX_SATURATION) & (val > CREAM_MIN_VALUE)).astype(np.uint8)
    dark = (val < DARK_MAX_VALUE).astype(np.uint8)
    filled = []
    for mask in (cream, dark):
        mask[:top] = 0
        mask[bottom:] = 0
        filled.append(_fill_holes(mask))
    return filled[0], filled[1]


GLYPH_HOLE_MIN_THICKNESS = 8  # 絵の穴の太さ(画素)。マスどうしの細い隙間はこれより細い


def _fill_holes(mask: NDArray[np.uint8]) -> NDArray[np.uint8]:
    """マスの中の絵で空いた穴だけを埋める。隣のマスとの細い隙間は埋めない。"""
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    outer = np.zeros_like(mask)
    cv2.drawContours(outer, contours, -1, 1, -1)
    holes = ((outer == 1) & (mask == 0)).astype(np.uint8)
    result = mask.copy()
    count, labels, stats, _ = cv2.connectedComponentsWithStats(holes, connectivity=8)
    for i in range(1, count):
        x0, y0, w, h, _ = (int(v) for v in stats[i])
        comp = (labels[y0 : y0 + h, x0 : x0 + w] == i).astype(np.uint8)
        thickness = cv2.distanceTransform(comp, cv2.DIST_L2, 5).max()
        if thickness >= GLYPH_HOLE_MIN_THICKNESS:
            result[y0 : y0 + h, x0 : x0 + w][comp == 1] = 1
    return result


ERODE_PX = 3  # 隣り合うマスを切り離すための侵食(画素)。マスの中心は変わらない
TILE_SEED_MIN_AREA = (
    6000  # 侵食後の面積の範囲(黒は約9,000〜12,000、白は約9,300〜13,600。隣り合う2マスは約18,000〜)
)
TILE_SEED_MAX_AREA = 15000  # 白の女王は絵の穴を埋めて約13,500
GLYPH_RADIUS = 0.85  # 絵を取る範囲: マス半径に対する比(輪郭を避ける)


LATTICE_FRACTION = 0.3  # 格子点の中心の周りで、地の色が占める割合の下限(駒がある)
LATTICE_RADIUS = 45  # 格子点の判定の円(画素)。マスの内側だけを見る
ANCHOR_TOLERANCE = 8.0  # 白のマスの中心が格子点からこれ以上ずれたら、格子が合っていないとみなす


def find_tiles(
    image: NDArray[np.uint8], top: int = BOARD_TOP, bottom: int = BOARD_BOTTOM
) -> list[Tile]:
    """マスの中心を探し、絵の色を集める。

    白系の地のマスを基準にして、盤の格子(軸座標)の全点を調べる。各点の中心の周りで、
    白系・黒系の地が占める割合を見る。マスがあれば割合が大きく、木目だけなら0になる。
    影や絵の線で隣と分かれていなくても、格子で数えられる。白のマスが1つも見えないときは、
    従来の方法(侵食による連結成分)に戻す。
    """
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    hue, sat, val = (hsv[:, :, i].astype(np.uint8) for i in range(3))
    cream, dark = ground_masks(image, top, bottom)
    anchors = _white_centres(cream)
    if not anchors:
        return _fallback_tiles(image, top, bottom, hue, sat, val)
    # 基準は、面積が中央値に近い白のマス(欠けや重なりで大きさが崩れたものを避ける)
    median_area = float(np.median([a for _, _, a in anchors]))
    ax, ay, _ = min(anchors, key=lambda t: abs(t[2] - median_area))
    disk = _disk(LATTICE_RADIUS)
    frac_c = cv2.filter2D(cream.astype(np.float32), -1, disk, borderType=cv2.BORDER_CONSTANT)
    frac_d = cv2.filter2D(dark.astype(np.float32), -1, disk, borderType=cv2.BORDER_CONSTANT)
    h, w = image.shape[:2]
    lattice: list[tuple[float, float]] = []
    tiles: list[Tile] = []
    for q in range(-16, 17):
        for r in range(-16, 17):
            cx = ax + 1.5 * TILE_R * q
            cy = ay + TILE_H * (r + q / 2)
            lattice.append((cx, cy))
            # 中心の円が盤の範囲に収まる点だけを見る(盤の端の手持ちの列を数えないため)
            if not (
                top + LATTICE_RADIUS <= cy < bottom - LATTICE_RADIUS
                and LATTICE_RADIUS <= cx < w - LATTICE_RADIUS
            ):
                continue
            ix, iy = int(round(cx)), int(round(cy))
            fc, fd = float(frac_c[iy, ix]), float(frac_d[iy, ix])
            if max(fc, fd) < LATTICE_FRACTION:
                continue
            side = Color.WHITE if fc >= fd else Color.BLACK
            tiles.append(
                Tile(
                    x=cx,
                    y=cy,
                    side=side,
                    area=int(max(fc, fd) * np.pi * LATTICE_RADIUS**2),
                    glyph_hsv=_glyph_pixels(hue, sat, val, cx, cy),
                )
            )
    # 白のマスが格子からずれていれば、盤の大きさが違う画面(説明など)。従来の方法に戻す
    for ax2, ay2, _ in anchors:
        if min(math.hypot(ax2 - lx, ay2 - ly) for lx, ly in lattice) > ANCHOR_TOLERANCE:
            return _fallback_tiles(image, top, bottom, hue, sat, val)
    return tiles


def _disk(radius: int) -> NDArray[np.float32]:
    size = 2 * radius + 1
    yy, xx = np.mgrid[0:size, 0:size]
    d = ((xx - radius) ** 2 + (yy - radius) ** 2 <= radius * radius).astype(np.float32)
    return np.asarray(d / d.sum(), dtype=np.float32)


def _white_centres(mask: NDArray[np.uint8]) -> list[tuple[float, float, int]]:
    """白系の地のマスの中心(侵食で隣と切り離した連結成分の重心)。"""
    eroded = cv2.erode(mask, np.ones((ERODE_PX, ERODE_PX), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(eroded, connectivity=8)
    out: list[tuple[float, float, int]] = []
    for i in range(1, count):
        x0, y0, w, h, area = (int(v) for v in stats[i])
        if not TILE_SEED_MIN_AREA <= area <= TILE_SEED_MAX_AREA:
            continue
        ys, xs = np.nonzero(labels[y0 : y0 + h, x0 : x0 + w] == i)
        out.append((x0 + float(xs.mean()), y0 + float(ys.mean()), area))
    return out


def _fallback_tiles(
    image: NDArray[np.uint8],
    top: int,
    bottom: int,
    hue: NDArray[np.uint8],
    sat: NDArray[np.uint8],
    val: NDArray[np.uint8],
) -> list[Tile]:
    """白のマスが見えないときの従来の方法(白と黒の両方を侵食で切り離して数える)。"""
    kernel = np.ones((ERODE_PX, ERODE_PX), np.uint8)
    tiles: list[Tile] = []
    for mask, side in zip(
        ground_masks(image, top, bottom), (Color.WHITE, Color.BLACK), strict=True
    ):
        eroded = cv2.erode(mask, kernel)
        count, labels, stats, _ = cv2.connectedComponentsWithStats(eroded, connectivity=8)
        for i in range(1, count):
            x0, y0, w, h, area = (int(v) for v in stats[i])
            if not TILE_SEED_MIN_AREA <= area <= TILE_SEED_MAX_AREA:
                continue
            ys, xs = np.nonzero(labels[y0 : y0 + h, x0 : x0 + w] == i)
            cx, cy = x0 + float(xs.mean()), y0 + float(ys.mean())
            tiles.append(
                Tile(
                    x=cx, y=cy, side=side, area=area, glyph_hsv=_glyph_pixels(hue, sat, val, cx, cy)
                )
            )
    return tiles


def _glyph_pixels(
    hue: NDArray[np.uint8], sat: NDArray[np.uint8], val: NDArray[np.uint8], cx: float, cy: float
) -> NDArray[np.uint8]:
    """マスの中心の周りで、絵の色(彩度と明度が高い画素)を集める。"""
    r = int(TILE_R * GLYPH_RADIUS)
    y0, x0 = max(0, int(cy) - r), max(0, int(cx) - r)
    hue_c = hue[y0 : int(cy) + r, x0 : int(cx) + r]
    sat_c = sat[y0 : int(cy) + r, x0 : int(cx) + r]
    val_c = val[y0 : int(cy) + r, x0 : int(cx) + r]
    yy, xx = np.mgrid[y0 : y0 + hue_c.shape[0], x0 : x0 + hue_c.shape[1]]
    inside = (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r
    glyph = inside & (sat_c > GLYPH_MIN_SATURATION) & (val_c > GLYPH_MIN_VALUE)
    return np.stack([hue_c[glyph], sat_c[glyph], val_c[glyph]], axis=1).astype(np.uint8)


def tile_hex_mask(
    shape: tuple[int, int], tiles: Sequence[Tile], scale: float = 1.0
) -> NDArray[np.uint8]:
    """各マスの六角形を塗った画像。残りの地の画素の確認に使う。"""
    canvas = np.zeros(shape, np.uint8)
    for t in tiles:
        pts = np.array(
            [
                [
                    t.x + TILE_R * scale * math.cos(math.radians(60 * k)),
                    t.y + TILE_R * scale * math.sin(math.radians(60 * k)),
                ]
                for k in range(6)
            ],
            np.int32,
        )
        cv2.fillPoly(canvas, [pts], 1)
    return canvas


def pixel_of(at: HexCoord, origin: tuple[float, float]) -> tuple[float, float]:
    """軸座標のマスの中心の画素。origin は (0,0) のマスの中心。"""
    x = origin[0] + 1.5 * TILE_R * at.q
    y = origin[1] + TILE_H * (at.r + at.q / 2)
    return x, y


def to_axial(tiles: Sequence[Tile]) -> dict[HexCoord, Tile] | None:
    """マスを軸座標に置く。左上のマスを (0,0) とする。

    まず公称の間隔で整数の位置を決め、次に最小二乗で間隔を合わせ直して、ずれを確かめる。
    間隔が合わない(拡大の違う表示など)、または位置が重なれば None。
    """
    if not tiles:
        return {}
    origin = min(tiles, key=lambda t: (t.y, t.x))
    cells: list[tuple[int, int, Tile]] = []
    for t in tiles:
        dx = t.x - origin.x
        q = round(dx / (1.5 * TILE_R))
        r = round((t.y - origin.y) / TILE_H - q / 2)
        cells.append((q, r, t))
    if len({(q, r) for q, r, _ in cells}) != len(cells):
        return None
    qs = np.array([q for q, _, _ in cells], dtype=float)
    half = np.array([r + q / 2 for q, r, _ in cells], dtype=float)
    dxs = np.array([t.x - origin.x for _, _, t in cells])
    dys = np.array([t.y - origin.y for _, _, t in cells])
    spacing_x = float((dxs * qs).sum() / (qs * qs).sum()) if (qs * qs).sum() > 0 else 1.5 * TILE_R
    spacing_y = (
        float((dys * half).sum() / (half * half).sum()) if (half * half).sum() > 0 else TILE_H
    )
    resid = np.maximum(np.abs(dxs - spacing_x * qs), np.abs(dys - spacing_y * half))
    if float(resid.max()) > FIT_TOLERANCE:
        return None
    return {HexCoord(q, r): t for q, r, t in cells}
