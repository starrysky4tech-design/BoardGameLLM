"""画面が変わったかの判定(ChangeDetector の実装)。

Kahuna は背景の波と鳥が常に動く。平均差分では静止中でも0.03〜0.07あるため、
「一定以上変わった画素の割合」で判定する。
"""

import cv2
import numpy as np

from bglm.core.models import Frame, Rect


class PixelRatioDetector:
    """画素差が pixel_delta 以上の画素が、領域の min_ratio を超えたら「変わった」とする。

    既定値は Phase 0 の Kahuna の実画像で決めた(.steering/20261030-phase0-feasibility)。
    静止中のフレーム間で最大0.069%、操作で変わったフレーム間で最小4.1%だったため、
    その間(0.5%)に置いた。小さな変化(ハイライトなど)は region で絞って判定する。
    """

    def __init__(self, pixel_delta: int = 32, min_ratio: float = 0.005) -> None:
        if not 0 <= pixel_delta <= 255:
            raise ValueError(f"pixel_delta は0〜255: {pixel_delta}")
        if not 0.0 <= min_ratio <= 1.0:
            raise ValueError(f"min_ratio は0.0〜1.0: {min_ratio}")
        self._pixel_delta = pixel_delta
        self._min_ratio = min_ratio

    def changed(self, before: Frame, after: Frame, region: Rect | None = None) -> bool:
        return self.ratio(before, after, region) > self._min_ratio

    def ratio(self, before: Frame, after: Frame, region: Rect | None = None) -> float:
        """変わった画素の割合(0.0〜1.0)。"""
        if (before.width, before.height) != (after.width, after.height):
            raise ValueError(
                f"画面の大きさが違う: {before.width}x{before.height} と {after.width}x{after.height}"
            )
        a, b = before.image, after.image
        if region is not None:
            top, left = region.top, region.left
            a = a[top : top + region.height, left : left + region.width]
            b = b[top : top + region.height, left : left + region.width]
        if a.size == 0:
            return 0.0
        diff = cv2.absdiff(a, b).max(axis=2)
        return float(np.count_nonzero(diff >= self._pixel_delta)) / diff.size
