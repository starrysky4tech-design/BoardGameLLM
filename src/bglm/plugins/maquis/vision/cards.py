"""巡回カードの画面(山札ボタンを押すと開く)から、カードの3つの地点を読む。

カード1枚は縦長の枠(幅 446 の間隔で並ぶ)で、①②③に地点の絵と名前が出る。名前は文字なので、絵を
テンプレート(data/templates/icons/)と比べて地点を決める。山札(左)と捨札(右)があり、捨札は新しい順に
左から並ぶ(実機で確認)。
"""

from functools import cache
from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray

from bglm.plugins.maquis.logic.patrol import PatrolCard
from bglm.plugins.maquis.vision import layout
from bglm.toolkit.images import gray, load_image
from bglm.toolkit.matching import best_match

ICON_DIR = Path(__file__).resolve().parent.parent / "data" / "templates" / "icons"
WINDOW_W = 120  # 絵の探索窓(幅)。テンプレートはこの中央を切り出してある
WINDOW_H = 85
MATCH_MIN = 0.85  # 絵の相関の下限
MARGIN_MIN = 0.05  # 1位の地点と、別の地点の最良との差の下限
BORDER_DARK = 70
BORDER_FRACTION = 0.9  # 枠線(縦に連続する濃い画素)の割合
BORDER_ROWS = (520, 900)
CARD_LEFT_SEARCH = 36  # 左枠の探索範囲の幅


@cache
def _icons() -> dict[str, list[NDArray[np.uint8]]]:
    out: dict[str, list[NDArray[np.uint8]]] = {}
    for path in sorted(ICON_DIR.glob("*.png")):
        image = load_image(path, cv2.IMREAD_GRAYSCALE)
        if image is not None:
            out.setdefault(path.stem.split("__")[0], []).append(image)
    return out


def find_left(image: NDArray[np.uint8], x_range: tuple[int, int]) -> int | None:
    """カードの左枠線(縦の濃い線)の x。`x_range` の中で最初のもの。無ければ None(カードが無い)。"""
    g = gray(image)
    x0, x1 = x_range
    y0, y1 = BORDER_ROWS
    fraction = np.mean(g[y0:y1, x0 : x1 + CARD_LEFT_SEARCH] < BORDER_DARK, axis=0)
    hits = np.nonzero(fraction >= BORDER_FRACTION)[0]
    return int(hits[0]) + x0 if len(hits) else None


def read_icon(window: NDArray[np.uint8]) -> tuple[str | None, float]:
    """絵の窓から地点を決める。確信が足りなければ (None, 最良の相関)。"""
    scores = sorted(
        (
            (max(best_match(window, t).score for t in templates), place)
            for place, templates in _icons().items()
        ),
        reverse=True,
    )
    if not scores:
        return None, 0.0
    best, place = scores[0]
    second = scores[1][0] if len(scores) > 1 else 0.0
    if best < MATCH_MIN or best - second < MARGIN_MIN:
        return None, best
    return place, best


def read_card(image: NDArray[np.uint8], left: int) -> tuple[PatrolCard | None, float]:
    """左枠が `left` のカードの3地点。1つでも読めなければ (None, 最小の相関)。"""
    g = gray(image)
    places: list[str] = []
    confidence = 1.0
    for y0, _ in layout.CARD_ICON_Y:
        x0 = left + layout.CARD_ICON_X[0]
        window = g[y0 : y0 + WINDOW_H, x0 : x0 + WINDOW_W]
        place, score = read_icon(window)
        confidence = min(confidence, score)
        if place is None:
            return None, confidence
        places.append(place)
    return (places[0], places[1], places[2]), confidence


def read_discard_top(image: NDArray[np.uint8]) -> tuple[PatrolCard | None, float, bool]:
    """捨札の先頭(最も新しい)カード。返り値は (カード, 確信度, 捨札にカードがあるか)。"""
    left = find_left(image, layout.DISCARD_FIRST_LEFT)
    if left is None:
        return None, 1.0, False
    card, confidence = read_card(image, left)
    return card, confidence, True
