"""餌箱のダイスの目の読み取り(全体ボードの表示。トレイの上にダイスが散らばる)。

サイコロ本体はクリーム色、面の絵(魚・虫・ネズミ・果実・種)は本体の中に現れる。
本体を輪郭で見つけ(触れ合うダイスは縮めて分け)、本体の中の絵の色を画素ごとに分類して、面を決める。
虫と種の 2 つの絵がある面は、どちらか 1 つを選ぶ面(INV_OR_SEED)。決められない面は UNKNOWN_FACE として返す
(推測しない)。ダイスの数は、本体の数。

絵の色(OpenCV の色相 0〜179、彩度・明度 0〜255)は、実画面の実測(2026-11-14):
果実 = 赤(色相 175、彩度 220)、種 = 橙(色相 15〜20、彩度 200、明度 170〜190)、虫 = 緑(色相 81、彩度 255、明度 80)、
魚 = 青緑(色相 94、彩度 255)、ネズミ = 暗い灰茶(色相 14、彩度 80、明度 107)。種とネズミは色相が近く、彩度と明度で分ける。
"""

from dataclasses import dataclass

import cv2
import numpy as np
from numpy.typing import NDArray

from bglm.plugins.wingspan.logic.models import INV_OR_SEED, Food
from bglm.plugins.wingspan.vision.mat import Image

Rect = tuple[int, int, int, int]
Mask = NDArray[np.bool_]
Gray = NDArray[np.uint8]

TRAY: Rect = (2030, 215, 2145, 445)  # 餌箱のトレイ(原寸)
UNKNOWN_FACE = "?"

_CREAM_MIN = 150  # 本体の明るさ(R、G、B の最小)
_CREAM_SPREAD = 75  # 本体の色の幅(クリームは彩度が低い)
_MIN_BODY_AREA = (
    350  # サイコロ 1 個の最小の面積(縮めた後。1 個は 550〜750、触れ合う 3 個でも各 480 以上)
)
_ERODE = 3  # 触れ合うダイスを分けるために縮める画素数(実測: 3 で 3 個・5 個が分かれる)
_MIN_ICON_PX = 20  # その色の画素がこれ以上あれば、その絵がある(影やスラッシュの線を除く)


@dataclass(frozen=True)
class Die:
    face: str  # Food の値、INV_OR_SEED、または UNKNOWN_FACE
    x: int  # 画像上の中心(原寸)
    y: int


def _cream(crop: Image) -> Mask:
    rgb = crop.astype(np.int16)
    spread = rgb.max(axis=2) - rgb.min(axis=2)
    return np.asarray((rgb.min(axis=2) >= _CREAM_MIN) & (spread <= _CREAM_SPREAD))


def _solid_bodies(cream: Mask) -> Gray:
    """クリーム色の領域を、絵の穴ごと塗りつぶした本体のマスク(穴が大きい絵も含める)。"""
    raw: Gray = cream.astype(np.uint8) * 255
    mask: Gray = np.asarray(
        cv2.morphologyEx(raw, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8)), dtype=np.uint8
    )
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    solid: Gray = np.zeros_like(mask)
    cv2.drawContours(solid, contours, -1, 255, thickness=cv2.FILLED)
    return solid


def _body_masks(solid: Gray) -> list[Gray]:
    kernel = np.ones((_ERODE * 2 + 1, _ERODE * 2 + 1), np.uint8)
    eroded = cv2.erode(solid, kernel)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(eroded, connectivity=8)
    bodies: list[Gray] = []
    for i in range(1, count):
        if stats[i, cv2.CC_STAT_AREA] >= _MIN_BODY_AREA:
            grown = cv2.dilate((labels == i).astype(np.uint8) * 255, kernel)
            bodies.append(np.asarray(cv2.bitwise_and(grown, solid)))  # 隣のダイスへ広げない
    return bodies


def _icon_counts(hsv: Gray, region: Mask) -> dict[str, int]:
    """本体の中の、絵の色ごとの画素数。"""
    h, s, v = (hsv[..., i].astype(np.int16) for i in range(3))
    classes = {
        Food.FRUIT.value: ((h >= 165) | (h <= 6)) & (s >= 120),
        Food.SEED.value: (h >= 10) & (h <= 24) & (s >= 150) & (v >= 140),
        Food.INVERTEBRATE.value: (h >= 68) & (h <= 87) & (s >= 150),
        Food.FISH.value: (h >= 88) & (h <= 108) & (s >= 150),
        Food.RODENT.value: (h >= 6) & (h <= 24) & (s >= 55) & (s <= 130) & (v <= 140),
    }
    return {name: int(np.count_nonzero(mask & region)) for name, mask in classes.items()}


def _face_of(counts: dict[str, int]) -> str:
    present = {name for name, n in counts.items() if n >= _MIN_ICON_PX}
    if present == {Food.INVERTEBRATE.value, Food.SEED.value}:
        return INV_OR_SEED
    if len(present) == 1:
        return next(iter(present))
    return UNKNOWN_FACE


def read_feeder(image: Image, tray: Rect = TRAY) -> list[Die]:
    """トレイの上のダイスを、上から順に返す(並びに意味は無い)。"""
    x0, y0, x1, y1 = tray
    crop = np.asarray(image[y0:y1, x0:x1])
    hsv: Gray = np.asarray(cv2.cvtColor(crop, cv2.COLOR_BGR2HSV))
    dice: list[Die] = []
    for body in _body_masks(_solid_bodies(_cream(crop))):
        inner: Mask = np.asarray(cv2.erode(body, np.ones((5, 5), np.uint8)) > 0)
        ys, xs = np.nonzero(body)
        face = _face_of(_icon_counts(hsv, inner))
        dice.append(Die(face, int(xs.mean()) + x0, int(ys.mean()) + y0))
    return sorted(dice, key=lambda d: (d.y, d.x))


def feeder_faces(image: Image) -> tuple[str, ...]:
    """餌箱のダイスの目を、昇順に並べて返す(logic の `WingspanState.feeder` と同じ形)。"""
    return tuple(sorted(d.face for d in read_feeder(image)))
