"""島のカフナコマ(丸い印)の検出。

自分の石(明るい縁)と相手の石(暗い縁)のテンプレートを、盤の全体に当てて、見つかった位置を
最も近い島に割り当てる。島ごとの石の位置は board.json にある(COCO だけ概算なので、許容を広めにしている)。
"""

import cv2
import numpy as np
from numpy.typing import NDArray

from bglm.plugins.kahuna.logic.models import BoardDef, Player
from bglm.plugins.kahuna.vision.sticks import MAP_ROI
from bglm.plugins.kahuna.vision.templates import TemplateSet

MIN_SCORE = 0.80  # 石と認めるテンプレートとの相関
MAX_DISTANCE = 90.0  # 島の石の位置から、検出位置までの許容距離
PEAK_RADIUS = 30  # 同じ石の重複検出を除く半径


def _peaks(score: NDArray[np.float32], threshold: float) -> list[tuple[int, int, float]]:
    found: list[tuple[int, int, float]] = []
    work = score.copy()
    while True:
        _, best, _, location = cv2.minMaxLoc(work)
        if best < threshold:
            return found
        x, y = location
        found.append((x, y, float(best)))
        work[
            max(0, y - PEAK_RADIUS) : y + PEAK_RADIUS, max(0, x - PEAK_RADIUS) : x + PEAK_RADIUS
        ] = -1


def find_stones(
    image: NDArray[np.uint8], board: BoardDef, templates: TemplateSet
) -> tuple[list[Player | None], list[float]]:
    """島ごとの石の持ち主と、検出のスコア(石が無い島は 0.0)。"""
    x0, y0, x1, y1 = MAP_ROI
    roi = image[y0:y1, x0:x1]
    owners: list[Player | None] = [None] * len(board.islands)
    scores = [0.0] * len(board.islands)
    for player, template in templates.stones.items():
        half = template.shape[0] // 2
        result = np.asarray(
            cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED), dtype=np.float32
        )
        for px, py, score in _peaks(result, MIN_SCORE):
            cx, cy = px + half + x0, py + half + y0
            distances = [float(np.hypot(cx - p.x, cy - p.y)) for p in board.stone_positions]
            island = int(np.argmin(distances))
            if distances[island] <= MAX_DISTANCE and score > scores[island]:
                owners[island], scores[island] = player, score
    return owners, scores
