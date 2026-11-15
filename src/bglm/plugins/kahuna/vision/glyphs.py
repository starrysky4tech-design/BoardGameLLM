"""白い文字(数字)の切り出しと、画面の色のマスク。

文字は白い塗りに黒い縁取りがある。縁取りの内側の白い連結成分を1文字として切り出し、
一定の大きさに正規化して、テンプレートと正規化相関で比べる。
"""

import cv2
import numpy as np
from numpy.typing import NDArray

from bglm.toolkit.components import component_mask, connected_components

GLYPH_SIZE = (24, 36)  # 幅, 高さ
WHITE_MIN = 215  # 文字の白: 全チャンネルがこの値以上
MIN_HEIGHT = 16
MIN_AREA = 50

# 赤(山札の丸、「READY FOR A NEW ROUND」の帯の模様): BGR の R が高く、G と B が低い
RED_MIN = 150
RED_OTHER_MAX = 110


def red_mask(image: NDArray[np.uint8]) -> NDArray[np.bool_]:
    """赤い画素(山札の丸、ラウンドの帯の模様)。"""
    return (
        (image[..., 2] > RED_MIN)
        & (image[..., 1] < RED_OTHER_MAX)
        & (image[..., 0] < RED_OTHER_MAX)
    )


def white_mask(roi: NDArray[np.uint8], circle: bool = False) -> NDArray[np.uint8]:
    """白い画素のマスク(0/255)。circle=True なら、領域の中心の円(半径22)の内側に限る。

    山札の数字は赤い丸の中にあり、丸の外には山札のカードの白い縁があるので、円で切る。
    """
    bright = (roi.min(axis=2) >= WHITE_MIN).astype(np.uint8) * 255
    if circle:
        inside = np.zeros(bright.shape, np.uint8)
        cv2.circle(inside, (bright.shape[1] // 2, bright.shape[0] // 2), 22, 255, -1)
        bright = np.asarray(cv2.bitwise_and(bright, inside), dtype=np.uint8)
    return bright


def extract_glyphs(mask: NDArray[np.uint8]) -> list[tuple[int, int, NDArray[np.uint8]]]:
    """連結成分ごとの (左端x, 右端x, 正規化した形)。小さすぎるものは捨てる。左から順。"""
    components, labels = connected_components(mask)
    found: list[tuple[int, int, NDArray[np.uint8]]] = []
    for c in components:
        if c.height < MIN_HEIGHT or c.area < MIN_AREA:
            continue
        shape = component_mask(labels, c) * 255
        glyph = np.asarray(
            cv2.resize(shape, GLYPH_SIZE, interpolation=cv2.INTER_AREA), dtype=np.uint8
        )
        found.append((c.x, c.x + c.width, glyph))
    return sorted(found, key=lambda g: g[0])


def group_by_gap(
    glyphs: list[tuple[int, int, NDArray[np.uint8]]], max_gap: int
) -> list[list[tuple[int, int, NDArray[np.uint8]]]]:
    """隣の文字との隙間が max_gap 以下のものを、1つの語(数)にまとめる。"""
    groups: list[list[tuple[int, int, NDArray[np.uint8]]]] = []
    for glyph in glyphs:
        if groups and glyph[0] - groups[-1][-1][1] <= max_gap:
            groups[-1].append(glyph)
        else:
            groups.append([glyph])
    return groups
