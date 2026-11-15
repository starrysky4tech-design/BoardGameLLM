"""全体ボードの読み取り: 枠ごとの札の有無と札名(02_DESIGN.md 論点 5)。

札の有無は、札の紙の色(明るく彩度の低いクリーム色)が枠にどれだけ広がるかで決める。
札名は、札の上端の帯を日本語の OCR で読み、札の表と照合する(`names.match_card`)。
読めない・表に無い札は UNKNOWN_CARD として持つ(推測で埋めない。02_DESIGN.md 論点 4)。
"""

from collections.abc import Callable
from dataclasses import dataclass

import cv2
import numpy as np
from numpy.typing import NDArray

from bglm.plugins.wingspan.logic.models import HABITATS, UNKNOWN_CARD, BirdCard, Habitat
from bglm.plugins.wingspan.vision.layout import card_rect, egg_centers, name_rect
from bglm.plugins.wingspan.vision.names import match_name

Image = NDArray[np.uint8]
# 領域を読み、行の文字列を上から順に返す(OCR の差し替え口。テストでは偽物を渡す)
LineReader = Callable[[Image, tuple[int, int, int, int]], list[str]]

PAPER_MIN_FRACTION = 0.40  # 枠の中で紙の色が占める割合がこれ以上なら、札がある
_PAPER_MIN_BRIGHTNESS = 170
_PAPER_MAX_SPREAD = 60  # R、G、B の最大と最小の差(彩度が低い = 灰色・クリーム色)


def paper_fraction(image: Image, rect: tuple[int, int, int, int]) -> float:
    """領域のうち、札の紙の色(明るく彩度が低い)の画素の割合。"""
    x0, y0, x1, y1 = rect
    crop = image[y0:y1, x0:x1].astype(np.int16)
    if crop.size == 0:
        return 0.0
    bright = crop.min(axis=2) >= _PAPER_MIN_BRIGHTNESS
    flat = (crop.max(axis=2) - crop.min(axis=2)) <= _PAPER_MAX_SPREAD
    return float(np.mean(bright & flat))


def has_card(image: Image, habitat: Habitat, column: int) -> bool:
    return paper_fraction(image, card_rect(habitat, column)) >= PAPER_MIN_FRACTION


@dataclass(frozen=True)
class SlotRead:
    habitat: Habitat
    column: int
    name: str  # 札の表の札名、読めなければ UNKNOWN_CARD
    text: str  # OCR の生の文字列(記録用)


def read_slot(
    image: Image, habitat: Habitat, column: int, read_lines: LineReader, birds: dict[str, BirdCard]
) -> SlotRead | None:
    """枠に札があれば、札名を読む。札が無ければ None。"""
    if not has_card(image, habitat, column):
        return None
    text = "".join(read_lines(image, name_rect(habitat, column)))
    found = match_name(text, birds)
    return SlotRead(habitat, column, found.name if found else UNKNOWN_CARD, text)


def read_rows(
    image: Image, read_lines: LineReader, birds: dict[str, BirdCard]
) -> dict[Habitat, list[SlotRead]]:
    """3 行の鳥を左から順に読む。鳥は左から詰めて置かれるので、札の無い枠に出会ったら、その行は終わり。"""
    rows: dict[Habitat, list[SlotRead]] = {}
    for habitat in HABITATS:
        found: list[SlotRead] = []
        for column in range(5):
            slot = read_slot(image, habitat, column, read_lines, birds)
            if slot is None:
                break
            found.append(slot)
        rows[habitat] = found
    return rows


# 満たされた卵の色(OpenCV の色相 0〜179、彩度・明度 0〜255)。実測: 黄金色。空きの枠は白い縁の楕円で、彩度が低い
_EGG_HUE = (12, 35)
_EGG_MIN_SAT = 70
_EGG_MIN_VAL = 150
_EGG_MIN_FRACTION = 0.30  # 枠の中心付近で、黄金色の画素がこれ以上なら、満たされている


def count_eggs(image: Image, habitat: Habitat, column: int) -> int:
    """札の下の帯で、満たされた卵(黄金色)の数。札があるときだけ呼ぶ。"""
    filled = 0
    for cx, cy in egg_centers(habitat, column):
        patch = image[cy - 7 : cy + 8, cx - 5 : cx + 6]
        hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
        hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]
        golden = (
            (hue >= _EGG_HUE[0])
            & (hue <= _EGG_HUE[1])
            & (sat >= _EGG_MIN_SAT)
            & (val >= _EGG_MIN_VAL)
        )
        if float(np.mean(golden)) >= _EGG_MIN_FRACTION:
            filled += 1
    return filled
