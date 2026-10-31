"""山札・ラウンド・得点の数字の読み取り。領域は原寸の座標で、目盛り付きの拡大画像で確認した。"""

import numpy as np
from numpy.typing import NDArray

from bglm.core.models import Reading
from bglm.plugins.kahuna.vision.glyphs import (
    extract_glyphs,
    group_by_gap,
    white_mask,
)
from bglm.plugins.kahuna.vision.templates import TemplateSet
from bglm.toolkit.template_reader import TemplateReader

DECK_ROI = (1040, 1006, 1088, 1054)  # 赤い丸(中心 1064,1030)の中
ROUND_ROI = (1378, 60, 1434, 125)
SCORE_LEFT_ROI = (255, 95, 345, 142)  # 相手。数字の後ろに「POINTS」が続く
SCORE_RIGHT_ROI = (2060, 95, 2132, 142)  # 自分。数字は「POINTS」の手前で終わる

DECK_PILE_ROI = (1010, 1000, 1120, 1075)  # 山札の赤い丸を含む領域
DECK_EMPTY_MAX_RED = 50  # 赤い画素がこれ未満なら山札が無い(実測: 山札ありは900以上、空は0)

MIN_DIGIT_SCORE = 0.70  # これ未満の相関の文字は、数字として信用しない
MAX_DIGIT_GAP = 7  # 同じ数の中の、桁と桁の隙間(原寸の画素数)


def _crop(image: NDArray[np.uint8], roi: tuple[int, int, int, int]) -> NDArray[np.uint8]:
    x0, y0, x1, y1 = roi
    return image[y0:y1, x0:x1]


def _read_digits(
    glyphs: list[tuple[int, int, NDArray[np.uint8]]],
    templates: dict[str, list[NDArray[np.uint8]]],
) -> Reading:
    """文字を左から数字に直す。1文字でも信用できなければ、value を空にして信頼度を下げる。"""
    if not glyphs:
        return Reading("", 0.0)
    reader = TemplateReader(templates)
    labels: list[str] = []
    scores: list[float] = []
    for _, _, glyph in glyphs:
        reading = reader.read(glyph)
        labels.append(reading.value)
        scores.append(reading.confidence)
    confidence = min(scores)
    if confidence < MIN_DIGIT_SCORE:
        return Reading("", confidence)
    return Reading("".join(labels), confidence)


def read_deck(image: NDArray[np.uint8], templates: TemplateSet) -> Reading:
    """山札の残り枚数(赤い丸の中の数字)。山札が尽きるとカードごと消えるので、0枚とする。"""
    pile = _crop(image, DECK_PILE_ROI).astype(np.int16)
    red = int(((pile[..., 2] > 150) & (pile[..., 1] < 110) & (pile[..., 0] < 110)).sum())
    if red < DECK_EMPTY_MAX_RED:
        return Reading("0", 1.0)
    glyphs = extract_glyphs(white_mask(_crop(image, DECK_ROI), circle=True))
    return _read_digits(glyphs, templates.digits["deck"])


def read_round(image: NDArray[np.uint8], templates: TemplateSet) -> Reading:
    """ラウンド(1〜3)。"""
    glyphs = extract_glyphs(white_mask(_crop(image, ROUND_ROI)))
    return (
        _read_digits(glyphs[:1], templates.digits["round"])
        if len(glyphs) == 1
        else Reading("", 0.0)
    )


def read_score(image: NDArray[np.uint8], templates: TemplateSet, mine: bool) -> Reading:
    """得点。自分(右上)は数字だけの領域、相手(左上)は数字の後ろの「POINTS」を除く。"""
    roi = SCORE_RIGHT_ROI if mine else SCORE_LEFT_ROI
    glyphs = extract_glyphs(white_mask(_crop(image, roi)))
    if not glyphs:
        return Reading("", 0.0)
    if mine:
        number = glyphs
    else:
        # 数字は領域の左端から始まる。隙間が空いたら、その先は「POINTS」の文字
        number = group_by_gap(glyphs, MAX_DIGIT_GAP)[0]
    return _read_digits(number, templates.digits["score"])
