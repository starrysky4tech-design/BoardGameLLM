"""札の右下のバッジ: 蓄えた餌(円形。色つきの餌の絵)と、差し込んだ札(四角。白い四角に黒い札の絵)。

どちらも札の右端から −40 px、下端から −50 px に出る(実画面 164a で測った)。1 枚の札にはどちらか一方。
- バッジの有無: バッジの中は白い。中心 20×20 の画素のうち、明るい(R、G、B が 215 以上)画素の割合で決める
  (実測: あり 0.68〜0.79、なし 0.07〜0.14。鳥の絵の暗い画素を桁と取り違えない)
- 種類: バッジの上のアイコン。差し込みは白い四角(白 0.17、色 0.00)、蓄えた餌は色のついた絵(色 0.18〜0.23、白 0.00)
- 数: 桁のテンプレート(digits)。バッジの数字は側面の数より小さい(高さ約 22 px)
種類か数が決められなければ None を入れて返す(推測しない)。バッジが無い札は None。
"""

from dataclasses import dataclass
from enum import StrEnum

import cv2
import numpy as np

from bglm.plugins.wingspan.logic.models import Habitat
from bglm.plugins.wingspan.vision.digits import Glyph, read_number
from bglm.plugins.wingspan.vision.layout import card_rect
from bglm.plugins.wingspan.vision.mat import Image

DX, DY = -40, -50  # 札の右下の角からバッジの中心まで
BADGE_DIGIT_MIN_H = 10
_BRIGHT_MIN = 215
_BADGE_MIN_BRIGHT = 0.45  # 中心の明るい画素の割合がこれ以上なら、バッジがある
_WHITE_MIN = 235  # 差し込みのアイコンの白い四角
_WHITE_FRACTION = 0.10
_COLOR_MIN_SAT = 100
_COLOR_FRACTION = 0.10
_ICON_OTHER_MAX = 0.05  # もう一方の特徴は、これ未満


class BadgeKind(StrEnum):
    CACHED = "cached"  # 蓄えた餌
    TUCKED = "tucked"  # 差し込んだ札


@dataclass(frozen=True)
class Badge:
    kind: BadgeKind | None  # 決められなければ None
    count: int | None  # 読めなければ None


def _center(habitat: Habitat, column: int) -> tuple[int, int]:
    _, _, x1, y1 = card_rect(habitat, column)
    return x1 + DX, y1 + DY


def _digit_rect(cx: int, cy: int) -> tuple[int, int, int, int]:
    # 桁はバッジの中心より少し下・右(実測: x が中心 −6〜+11、y が −6〜+16)。縁や鳥の絵の暗い画素を入れない大きさ
    return (cx - 7, cy - 8, cx + 13, cy + 18)


def _has_badge(image: Image, cx: int, cy: int) -> bool:
    inner = image[cy - 10 : cy + 10, cx - 10 : cx + 10]
    return inner.size > 0 and float(np.mean(inner.min(axis=2) >= _BRIGHT_MIN)) >= _BADGE_MIN_BRIGHT


def _icon_kind(image: Image, cx: int, cy: int) -> BadgeKind | None:
    patch = image[cy - 32 : cy - 10, cx - 12 : cx + 12]
    if patch.size == 0:
        return None
    white = float(np.mean(patch.min(axis=2) >= _WHITE_MIN))
    colored = float(np.mean(cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)[..., 1] >= _COLOR_MIN_SAT))
    if white >= _WHITE_FRACTION and colored < _ICON_OTHER_MAX:
        return BadgeKind.TUCKED
    if colored >= _COLOR_FRACTION and white < _ICON_OTHER_MAX:
        return BadgeKind.CACHED
    return None


def read_badge(
    image: Image, habitat: Habitat, column: int, templates: dict[str, Glyph] | None = None
) -> Badge | None:
    """札の右下のバッジ。無ければ None。札があるときだけ呼ぶ。"""
    cx, cy = _center(habitat, column)
    if not _has_badge(image, cx, cy):
        return None
    count = read_number(image, _digit_rect(cx, cy), templates, BADGE_DIGIT_MIN_H)
    return Badge(_icon_kind(image, cx, cy), count)
