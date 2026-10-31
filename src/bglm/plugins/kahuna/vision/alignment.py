"""画面の位置合わせ。端末の表示が録画と横にずれることがあるため、認識の前に録画の座標へ戻す。

基準は「FISHERMAN」の名前(左上)。枚数や得点で変わらず、録画の座標で固定の位置にある。
ずれが見つからない(一致度が低い、ずれが大きすぎる)ときは None を返し、呼び出し側は操作せず止める。

座標の約束: 録画の座標 = 取得画像の座標 - (dx, dy)。タップは録画の座標に (dx, dy) を足して送る。
"""

from dataclasses import dataclass

import cv2
import numpy as np
from numpy.typing import NDArray

from bglm.core.models import Point

ANCHOR_BOX = (200, 55, 370, 95)  # 録画の座標(x0, y0, x1, y1)。基準の模様を切り出した位置
SEARCH_ROWS = 200  # 基準を探す上端の範囲(行)
MIN_SCORE = 0.90  # 基準との正規化相関。実測は一致 1.0
MAX_SHIFT = 200  # これより大きいずれは、別の画面として扱う(画素)


@dataclass(frozen=True)
class Alignment:
    dx: int
    dy: int
    score: float

    def to_screen(self, point: Point) -> Point:
        """録画の座標の点を、取得画像の座標(タップに使う)に直す。"""
        return Point(point.x + self.dx, point.y + self.dy)


def find_alignment(image: NDArray[np.uint8], anchor: NDArray[np.uint8]) -> Alignment | None:
    """取得画像の中で基準の模様が録画から何画素ずれているかを求める。見つからなければ None。"""
    gray = np.asarray(cv2.cvtColor(image[:SEARCH_ROWS], cv2.COLOR_BGR2GRAY), dtype=np.uint8)
    result = cv2.matchTemplate(gray, anchor, cv2.TM_CCOEFF_NORMED)
    _, best, _, (x, y) = cv2.minMaxLoc(result)
    if best < MIN_SCORE:
        return None
    dx, dy = x - ANCHOR_BOX[0], y - ANCHOR_BOX[1]
    if abs(dx) > MAX_SHIFT or abs(dy) > MAX_SHIFT:
        return None
    return Alignment(dx, dy, float(best))


def apply_alignment(image: NDArray[np.uint8], alignment: Alignment) -> NDArray[np.uint8]:
    """取得画像を録画の座標へ平行移動する。はみ出した部分は黒で埋める(録画の黒い帯と同じ)。"""
    matrix = np.array([[1.0, 0.0, -alignment.dx], [0.0, 1.0, -alignment.dy]], dtype=np.float64)
    height, width = image.shape[:2]
    shifted = cv2.warpAffine(image, matrix, (width, height), borderValue=0)
    return np.asarray(shifted, dtype=np.uint8)


def aligned_view(
    image: NDArray[np.uint8], anchor: NDArray[np.uint8]
) -> tuple[NDArray[np.uint8], Alignment] | None:
    """録画の座標に揃えた画像と、そのずれ。基準が見つからなければ None。"""
    alignment = find_alignment(image, anchor)
    if alignment is None:
        return None
    return apply_alignment(image, alignment), alignment
