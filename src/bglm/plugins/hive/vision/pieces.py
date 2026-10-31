"""マスの絵の色から駒の種類を決める(docs/04 の vision/pieces.py)。

駒の種類は絵の色で決まり、地の色(白系・黒系)は側を表す。基準の色はアプリ(SHG11、1080x2432)の
画面で測った中央値(HSVは OpenCV の値域: 色相 0〜179、彩度・明度 0〜255)。
"""

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from bglm.plugins.hive.logic.models import Kind

MIN_GLYPH_PIXELS = 300  # 絵の画素がこれより少なければ判定しない(空きマスや隠れた駒)
HUE_SCALE = 10.0  # 色相の差を、この角度で1とみなす
VALUE_SCALE = 60.0  # 明度の差を、この値で1とみなす
TOLERANCE = 0.5  # 基準との距離がこれ以上なら、確信度は0

# 種類 → (色相の中央値, 明度の中央値)
REFERENCE: dict[Kind, tuple[float, float]] = {
    Kind.QUEEN: (19.0, 255.0),  # 橙(明るい)
    Kind.SPIDER: (12.0, 135.0),  # 茶(暗い橙)
    Kind.ANT: (100.0, 191.0),  # 青
    Kind.GRASSHOPPER: (54.0, 157.0),  # 緑
    Kind.BEETLE: (132.0, 164.0),  # 紫
}


@dataclass(frozen=True)
class KindReading:
    kind: Kind | None  # 判定できなければ None
    confidence: float  # 0.0〜1.0


def _hue_distance(a: float, b: float) -> float:
    d = abs(a - b) % 180.0
    return min(d, 180.0 - d)


def classify(glyph_hsv: NDArray[np.uint8]) -> KindReading:
    if len(glyph_hsv) < MIN_GLYPH_PIXELS:
        return KindReading(None, 0.0)
    hue = float(np.median(glyph_hsv[:, 0]))
    val = float(np.median(glyph_hsv[:, 2]))
    best_kind: Kind | None = None
    best = float("inf")
    for kind, (ref_hue, ref_val) in REFERENCE.items():
        dist = _hue_distance(hue, ref_hue) / HUE_SCALE + abs(val - ref_val) / VALUE_SCALE
        if dist < best:
            best, best_kind = dist, kind
    confidence = max(0.0, 1.0 - best / TOLERANCE)
    return KindReading(best_kind, confidence)
