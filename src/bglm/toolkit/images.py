"""画像ファイルの読み込みと、画像の小さな定型(グレースケール、領域の切り出し)。

読み込みは `np.fromfile` + `cv2.imdecode` で行う。`cv2.imread` は、日本語を含むパスを読めないため。
読めないときに何を投げるかは、呼び出し側が決める(テンプレートの欠落を設定の誤りとするか、飛ばすかはゲームによる)。
"""

from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray

Box = tuple[int, int, int, int]  # (x0, y0, x1, y1)。右端・下端は含まない


def load_image(path: Path, flags: int = cv2.IMREAD_COLOR) -> NDArray[np.uint8] | None:
    """画像を読む。ファイルが無い、または画像として読めなければ None。"""
    try:
        data = np.fromfile(path, dtype=np.uint8)
    except OSError:
        return None
    image = cv2.imdecode(data, flags)
    if image is None:
        return None
    return np.asarray(image, dtype=np.uint8)


def gray(image: NDArray[np.uint8]) -> NDArray[np.uint8]:
    """BGR の画像をグレースケールにする。"""
    return np.asarray(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), dtype=np.uint8)


def crop(image: NDArray[np.uint8], box: Box) -> NDArray[np.uint8]:
    """領域 (x0, y0, x1, y1) を切り出す(複製しない)。"""
    x0, y0, x1, y1 = box
    return image[y0:y1, x0:x1]
