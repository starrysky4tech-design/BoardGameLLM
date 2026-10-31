"""段階的な読み取り。軽い手段から順に試し、信頼度が閾値以上になった時点で打ち切る。"""

from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

from bglm.core.models import Reading
from bglm.core.protocols import ElementReader


class ReaderChain:
    """readers を順に試す。どれも閾値に届かなければ、最も信頼度の高い結果を返す(呼び出し側が判断する)。"""

    def __init__(self, readers: Sequence[ElementReader], min_confidence: float) -> None:
        if not readers:
            raise ValueError("readers が空")
        if not 0.0 <= min_confidence <= 1.0:
            raise ValueError(f"min_confidence は0.0〜1.0: {min_confidence}")
        self._readers = list(readers)
        self._min_confidence = min_confidence

    def read(self, patch: NDArray[np.uint8]) -> Reading:
        best: Reading | None = None
        for reader in self._readers:
            reading = reader.read(patch)
            if reading.confidence >= self._min_confidence:
                return reading
            if best is None or reading.confidence > best.confidence:
                best = reading
        assert best is not None
        return best
