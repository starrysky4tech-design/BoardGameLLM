"""テンプレートマッチングによる `ElementReader`。ラベルごとの形(複数可)と、切り出した1要素を比べる。"""

import numpy as np
from numpy.typing import NDArray

from bglm.core.models import Reading
from bglm.toolkit.matching import match_score


class TemplateReader:
    """正規化相関が最も高いラベルを返す。信頼度はその相関(0〜1)。"""

    def __init__(self, templates: dict[str, list[NDArray[np.uint8]]]) -> None:
        if not templates or any(not variants for variants in templates.values()):
            raise ValueError("テンプレートが空のラベルがある")
        self._templates = templates

    def read(self, patch: NDArray[np.uint8]) -> Reading:
        best_label, best_score = "", 0.0
        for label, variants in self._templates.items():
            for template in variants:
                score = match_score(patch, template)
                if score > best_score:
                    best_label, best_score = label, score
        return Reading(best_label, min(best_score, 1.0))
