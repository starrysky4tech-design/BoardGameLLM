"""場札(下端の3枚)と手札(右の束)の名前の読み取り。

場札の文字はまっすぐで、位置も決まっている。手札はカードが扇形に傾いて重なるので、傾けた
テンプレートで探す。一番後ろの1枚は、他のカードに隠れて端しか見えないことがあり、その
カードは読めない(未判明として数える)。手札はアルファベット順に並ぶので、列の先頭の
カードの左に端が見えていれば、隠れた1枚があると分かる。
"""

from dataclasses import dataclass

import cv2
import numpy as np
from numpy.typing import NDArray

from bglm.plugins.kahuna.vision.templates import TemplateSet
from bglm.toolkit.images import crop, gray
from bglm.toolkit.matching import correlation, find_peaks, match_score

# --- 場札 ---
MARKET_SLOT_X = (1185, 1390, 1600)  # 3枚の左端(原寸)
MARKET_SLOT_W = 195
MARKET_NAME_Y, MARKET_NAME_H = 1012, 56
MARKET_MARGIN = (20, 8, 12)  # 左右の余白、上下の余白(テンプレートを少し小さくして、ずれを許す)
MARKET_MIN_SCORE = 0.60
MARKET_MIN_MARGIN = 0.05  # 1位と2位の差。小さいと取り違えやすい

# --- 手札 ---
HAND_ROI = (1620, 200, 2010, 960)  # x0, y0, x1, y1(原寸)
HAND_ANGLES = (-12, -8, -4, 0, 4, 8, 12)  # カードの傾き(度)
HAND_SCALES = (0.95, 1.0, 1.1)  # 手前のカードほど大きい
HAND_MIN_SCORE = 0.58
HAND_MIN_DISTANCE = 38  # 同じカードの重複検出を除く距離
HAND_PEAK_HALF = (40, 20)  # 同じ傾きの照合で、拾った山の周りを消す範囲(横, 縦の半分)


@dataclass(frozen=True)
class CardReading:
    island: int
    score: float
    x: int  # 名前の中心(原寸)
    y: int


def _present(slot: NDArray[np.uint8]) -> bool:
    """カードの白い縁や名前の白い文字が、十分にあるか(空き枠は海だけ)。"""
    white = np.count_nonzero(slot.min(axis=2) > 205)
    return bool(white > 0.06 * slot.shape[0] * slot.shape[1])


def read_market(
    image: NDArray[np.uint8], templates: TemplateSet
) -> tuple[list[CardReading | None], float]:
    """場札3枠の、島と信頼度。空き枠は None。返り値の信頼度は、読めた枠のスコアの最小値(無ければ1.0)。"""
    cut_x, cut_top, cut_x2 = MARKET_MARGIN
    readings: list[CardReading | None] = []
    confidences: list[float] = []
    for x in MARKET_SLOT_X:
        y0 = MARKET_NAME_Y
        slot = image[y0 : y0 + MARKET_NAME_H, x + cut_x : x + MARKET_SLOT_W - cut_x]
        if not _present(slot):
            readings.append(None)
            continue
        slot_gray = gray(slot)
        scores = {
            island: match_score(slot_gray, template[cut_top:-cut_top, cut_x2:-cut_x2])
            for island, template in templates.names.items()
        }
        ranked = sorted(scores.items(), key=lambda item: -item[1])
        (best, best_score), second_score = ranked[0], ranked[1][1]
        confident = (
            best_score >= MARKET_MIN_SCORE and best_score - second_score >= MARKET_MIN_MARGIN
        )
        readings.append(
            CardReading(best, best_score, x + MARKET_SLOT_W // 2, y0 + MARKET_NAME_H // 2)
        )
        confidences.append(best_score if confident else 0.0)
    return readings, (min(confidences) if confidences else 1.0)


def _rotated(template: NDArray[np.uint8], angle: float, scale: float) -> NDArray[np.uint8]:
    h, w = template.shape
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, scale)
    return np.asarray(
        cv2.warpAffine(
            template, matrix, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE
        ),
        dtype=np.uint8,
    )


def read_hand(image: NDArray[np.uint8], templates: TemplateSet) -> list[CardReading]:
    """手札の名前を、傾けたテンプレートで探す。上から下の順(アルファベット順に並ぶ)。"""
    x0, y0, _, _ = HAND_ROI
    hand_gray = gray(crop(image, HAND_ROI))
    half_w, half_h = HAND_PEAK_HALF
    candidates: list[CardReading] = []
    for island, template in templates.names.items():
        core = template[8:-8, 12:-12]
        for angle in HAND_ANGLES:
            for scale in HAND_SCALES:
                rotated = _rotated(core, angle, scale)
                if rotated.shape[0] >= hand_gray.shape[0] or rotated.shape[1] >= hand_gray.shape[1]:
                    continue
                result = correlation(hand_gray, rotated)
                for peak in find_peaks(result, HAND_MIN_SCORE, half_w, half_h):
                    candidates.append(
                        CardReading(
                            island,
                            peak.score,
                            peak.x + rotated.shape[1] // 2 + x0,
                            peak.y + rotated.shape[0] // 2 + y0,
                        )
                    )
    # 近い位置の重複(別の島の名前や、傾きの違い)は、スコアの高い方を残す
    candidates.sort(key=lambda c: -c.score)
    kept: list[CardReading] = []
    for candidate in candidates:
        if all(np.hypot(candidate.x - k.x, candidate.y - k.y) >= HAND_MIN_DISTANCE for k in kept):
            kept.append(candidate)
    return sorted(kept, key=lambda c: c.y)
