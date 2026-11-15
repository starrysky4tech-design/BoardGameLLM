"""取得画像の大きさ。座標を原寸で持つ読み取りは、大きさが違う画像を読まない(ずれた座標で読まないため)。"""

import numpy as np
from numpy.typing import NDArray

LANDSCAPE_SIZE = (2432, 1080)  # 幅, 高さ。端末 SHG11 の横向き(Kahuna、Monopoly)


def has_size(image: NDArray[np.uint8], size: tuple[int, int] = LANDSCAPE_SIZE) -> bool:
    """画像の大きさが size(幅, 高さ)と一致するか。"""
    return image.shape[:2] == (size[1], size[0])
