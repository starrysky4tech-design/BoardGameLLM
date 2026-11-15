"""2 値画像の連結成分(8 近傍)を、箱・面積・重心の一覧にする。

大きさや面積での絞り込みは、ゲームの知識なので呼び出し側で行う。
"""

from dataclasses import dataclass

import cv2
import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class Component:
    label: int  # ラベル画像の値
    x: int
    y: int
    width: int
    height: int
    area: int  # 画素数
    cx: float  # 重心
    cy: float


def connected_components(
    mask: NDArray[np.uint8],
) -> tuple[list[Component], NDArray[np.int32]]:
    """背景(0)を除く成分の一覧(ラベルの順)と、ラベル画像。"""
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    components = [
        Component(
            label=i,
            x=int(stats[i, cv2.CC_STAT_LEFT]),
            y=int(stats[i, cv2.CC_STAT_TOP]),
            width=int(stats[i, cv2.CC_STAT_WIDTH]),
            height=int(stats[i, cv2.CC_STAT_HEIGHT]),
            area=int(stats[i, cv2.CC_STAT_AREA]),
            cx=float(centroids[i, 0]),
            cy=float(centroids[i, 1]),
        )
        for i in range(1, count)
    ]
    return components, np.asarray(labels, dtype=np.int32)


def component_mask(labels: NDArray[np.int32], component: Component) -> NDArray[np.uint8]:
    """成分の箱の中で、その成分の画素を 1、他を 0 にした画像。"""
    x, y = component.x, component.y
    box = labels[y : y + component.height, x : x + component.width]
    return np.asarray(box == component.label, dtype=np.uint8)
