"""島のカフナコマ(丸い印)の検出。

自分の石(明るい縁)と相手の石(暗い縁)のテンプレートを、盤の全体に当てて、見つかった位置を
最も近い島に割り当てる。島ごとの石の位置は board.json にある(COCO だけ概算なので、許容を広めにしている)。
"""

import numpy as np
from numpy.typing import NDArray

from bglm.plugins.kahuna.logic.models import BoardDef, Player
from bglm.plugins.kahuna.vision.sticks import MAP_ROI
from bglm.plugins.kahuna.vision.templates import TemplateSet
from bglm.toolkit.images import crop
from bglm.toolkit.matching import correlation, find_peaks

MIN_SCORE = 0.80  # 石と認めるテンプレートとの相関
MAX_DISTANCE = 90.0  # 島の石の位置から、検出位置までの許容距離
PEAK_RADIUS = 30  # 同じ石の重複検出を除く半径


def find_stones(
    image: NDArray[np.uint8], board: BoardDef, templates: TemplateSet
) -> tuple[list[Player | None], list[float]]:
    """島ごとの石の持ち主と、検出のスコア(石が無い島は 0.0)。"""
    x0, y0, _, _ = MAP_ROI
    roi = crop(image, MAP_ROI)
    owners: list[Player | None] = [None] * len(board.islands)
    scores = [0.0] * len(board.islands)
    for player, template in templates.stones.items():
        half = template.shape[0] // 2
        result = correlation(roi, template)
        for peak in find_peaks(result, MIN_SCORE, PEAK_RADIUS, PEAK_RADIUS):
            cx, cy = peak.x + half + x0, peak.y + half + y0
            distances = [float(np.hypot(cx - p.x, cy - p.y)) for p in board.stone_positions]
            island = int(np.argmin(distances))
            if distances[island] <= MAX_DISTANCE and peak.score > scores[island]:
                owners[island], scores[island] = player, peak.score
    return owners, scores
