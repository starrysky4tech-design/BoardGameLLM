"""Monopoly の静止した盤のダイスの目を読む。座標は原寸(2432x1080)。

ダイスは黒い立方体で、斜め上から見える。上の面(大きい)と手前の面(低い)に、白い点が並ぶ。
上の面の点だけを数えて、ダイスの目とする。

- 点: 3 色とも 250 以上の「純白」の画素を 4 個以上含む、小さな明るい塊(幅 3〜9、高さ 2〜9)。
  手前の面の点は平たく、純白の画素が 0〜2 個しかない。盤の白っぽい物(マスコットの目やひげ)は、
  青の成分が 230 までしか上がらず、純白の画素を含まない
- 点の周り(半径 4.5 px の 8 方向)のうち、4 方向以上が暗い(輝度 80 未満)。黒いダイスの上の点だけを通す
- ダイス: 点を、距離 20 px 以内でまとめる。2 の目は対角の 2 点が約 20 px 離れるため、この距離にする
- 点が 6 個より多い塊は、接した 2 個のダイスとみなして、k-means で 2 つに分ける

読めないとき(ダイスが 2 個でない、目が 1〜6 でない、点が 12 個を超える、盤の地の色が領域の
40% に満たない)は、値を埋めずに不明を返す。カードやダイアログが盤を覆うと、文字の穴(O や D の内側)を
点と取り違えるため、盤の地の色の割合で弾く。
ダイスの動きが止まってから読む。通常の盤の表示(カメラ固定)の画像だけが対象。
"""

from dataclasses import dataclass

import cv2
import numpy as np
from numpy.typing import NDArray

from bglm.toolkit.components import connected_components

REGION = (900, 250, 1620, 820)  # x0, y0, x1, y1。盤の内側(ダイスが止まる範囲)
BRIGHT_THR = 170  # 点の塊の輝度の下限
PURE_THR = 250  # 純白とみなす、3 色の最小値の下限
PURE_MIN = 5  # 点の塊に含まれる純白の画素の下限(上の面 6〜15、手前の面 0〜2)
PIP_W = (3, 9)
PIP_H = (2, 9)
PIP_AREA_MIN = 4
RING_RADIUS = 4.5
RING_DARK_MAX = 80  # 周りが暗い、の輝度の上限
RING_DARK_MIN = (
    4  # 8 方向のうち、暗い方向の下限(5 だと、上の縁に近い点を落とす。3 だと余分な点を拾う)
)
LINK = 20  # 同じダイスの点どうしの距離の上限(px、各軸)
PIP_MIN, PIP_MAX = 1, 6
MAX_PIPS = 12
BOARD_GREEN = (206, 231, 206)  # 盤の地の色(BGR)
GREEN_TOL = 18
GREEN_MIN = 0.4  # 領域のうち、盤の地の色の画素の割合の下限(通常 0.62〜0.69、ダイアログ 0.08)


@dataclass(frozen=True)
class DiceReading:
    values: tuple[int, ...] | None  # ダイスごとの目。読めなければ None(左から順)

    @property
    def total(self) -> int | None:
        return sum(self.values) if self.values else None


UNKNOWN = DiceReading(None)

Point = tuple[float, float]


def find_pips(image: NDArray[np.uint8]) -> list[Point]:
    """上の面の点の中心を返す。"""
    x0, y0, x1, y1 = REGION
    gray = np.asarray(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), dtype=np.uint8)
    pure = image.min(axis=2) >= PURE_THR
    bright = (gray > BRIGHT_THR).astype(np.uint8)
    pips: list[Point] = []
    for c in connected_components(bright)[0]:
        x, y, w, h = c.x, c.y, c.width, c.height
        if not (x0 <= x <= x1 and y0 <= y <= y1):
            continue
        if not (PIP_W[0] <= w <= PIP_W[1] and PIP_H[0] <= h <= PIP_H[1] and c.area >= PIP_AREA_MIN):
            continue
        if int(pure[y : y + h, x : x + w].sum()) < PURE_MIN:
            continue
        if _dark_directions(gray, c.cx, c.cy) >= RING_DARK_MIN:
            pips.append((c.cx, c.cy))
    return pips


def _board_fraction(image: NDArray[np.uint8]) -> float:
    x0, y0, x1, y1 = REGION
    region = image[y0:y1, x0:x1].astype(np.int16)
    diff = np.abs(region - np.array(BOARD_GREEN, dtype=np.int16)).max(axis=2)
    return float((diff <= GREEN_TOL).mean())


def _dark_directions(gray: NDArray[np.uint8], cx: float, cy: float) -> int:
    dark = 0
    for angle in range(0, 360, 45):
        rx = int(round(cx + RING_RADIUS * np.cos(np.radians(angle))))
        ry = int(round(cy + RING_RADIUS * np.sin(np.radians(angle))))
        if 0 <= ry < gray.shape[0] and 0 <= rx < gray.shape[1] and gray[ry, rx] < RING_DARK_MAX:
            dark += 1
    return dark


def group_pips(pips: list[Point]) -> list[list[Point]]:
    """距離でまとめる。各軸の差が LINK 以内の点は同じダイス。"""
    groups: list[list[Point]] = []
    for pip in pips:
        linked = [
            g
            for g in groups
            if any(abs(pip[0] - q[0]) <= LINK and abs(pip[1] - q[1]) <= LINK for q in g)
        ]
        if not linked:
            groups.append([pip])
            continue
        linked[0].append(pip)
        for other in linked[1:]:
            linked[0].extend(other)
            groups.remove(other)
    return groups


def _split_in_two(group: list[Point]) -> list[list[Point]]:
    data = np.array(group, dtype=np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 0.5)
    _, labels, _ = cv2.kmeans(data, 2, None, criteria, 10, cv2.KMEANS_PP_CENTERS)  # type: ignore[call-overload]
    flat = labels.ravel()
    return [[group[i] for i in range(len(group)) if flat[i] == k] for k in (0, 1)]


def read_with_pips(image: NDArray[np.uint8]) -> tuple[DiceReading, tuple[Point, ...]]:
    """ダイスの目と、上の面の点の座標(左から順)を返す。読めないときの目は UNKNOWN、座標は空。

    座標は、静止の判定(連続 2 回で同じ位置)と、「今回振った出目か」の判定(前の画面と点が動いたか)に使う。
    """
    if _board_fraction(image) < GREEN_MIN:
        return UNKNOWN, ()
    pips = find_pips(image)
    if len(pips) > MAX_PIPS:
        return UNKNOWN, ()
    groups: list[list[Point]] = []
    for group in group_pips(pips):
        groups.extend(_split_in_two(group) if len(group) > PIP_MAX else [group])
    if len(groups) != 2:
        return UNKNOWN, ()
    ordered = sorted(groups, key=lambda g: sum(p[0] for p in g) / len(g))
    values = tuple(len(g) for g in ordered)
    if not all(PIP_MIN <= v <= PIP_MAX for v in values):
        return UNKNOWN, ()
    return DiceReading(values), tuple(sorted(p for g in ordered for p in g))


def read_dice(image: NDArray[np.uint8]) -> DiceReading:
    """静止した盤の画像(原寸 BGR)から、ダイスの目を読む。2 個のダイスが読めたときだけ値を返す。"""
    return read_with_pips(image)[0]
