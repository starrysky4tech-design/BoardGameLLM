"""右端の数(キューブ、餌 5 種)の読み取り: 桁の切り出しとテンプレート照合。

既定の OCR は、このフォントの「4」を「L」と誤る(RESULT.md の確認で再現)ので、桁のテンプレートで読む。
数字は濃い茶色のインクで、背景は淡い紙の色。位置は全体ボードの表示で固定(layout.COUNTER_ROWS)。
テンプレートは `data/templates/digits/<桁>.png`(保存画面から集めた。scripts/wingspan/build_digit_templates.py)。
読めなければ None を返す(推測しない)。
"""

from dataclasses import dataclass
from functools import cache
from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray

from bglm.plugins.wingspan.vision.mat import Image

Rect = tuple[int, int, int, int]
Glyph = NDArray[np.uint8]

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "data" / "templates" / "digits"
GLYPH_SIZE = (24, 32)  # 照合するときの桁の大きさ(幅, 高さ)
INK_MAX = 120  # これ以下の明るさをインクとする
MIN_SCORE = 0.70  # 照合の類似度の下限
MIN_MARGIN = 0.05  # 1 位と 2 位の差の下限
MIN_GLYPH_PX = 25  # 桁として数える最小の面積(ごみを除く)
MIN_GLYPH_H = 18  # 桁の最小の高さ(枠線や飾りを除く。桁の高さは約 30)
MAX_GLYPH_W = 30  # 桁の最大の幅(横に長い線を除く)


def ink_mask(image: Image, rect: Rect) -> NDArray[np.uint8]:
    x0, y0, x1, y1 = rect
    gray = cv2.cvtColor(image[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    return np.asarray((gray <= INK_MAX).astype(np.uint8) * 255)


def segment_glyphs(image: Image, rect: Rect, min_height: int = MIN_GLYPH_H) -> list[Glyph]:
    """領域のインクを、左から順に桁ごとに切り出して、GLYPH_SIZE に揃える。"""
    mask = ink_mask(image, rect)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    boxes = [
        (int(stats[i, 0]), int(stats[i, 1]), int(stats[i, 2]), int(stats[i, 3]))
        for i in range(1, count)
        if stats[i, cv2.CC_STAT_AREA] >= MIN_GLYPH_PX
        and stats[i, cv2.CC_STAT_HEIGHT] >= min_height
        and stats[i, cv2.CC_STAT_WIDTH] <= MAX_GLYPH_W
    ]
    glyphs: list[Glyph] = []
    for x, y, w, h in sorted(boxes):
        crop = mask[y : y + h, x : x + w]
        glyphs.append(np.asarray(cv2.resize(crop, GLYPH_SIZE, interpolation=cv2.INTER_AREA)))
    return glyphs


@cache
def load_templates(directory: Path = TEMPLATE_DIR) -> dict[str, Glyph]:
    templates: dict[str, Glyph] = {}
    for path in sorted(directory.glob("*.png")):
        image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if image is not None:
            templates[path.stem] = np.asarray(image)
    return templates


@dataclass(frozen=True)
class Digit:
    value: str
    score: float
    margin: float


def classify_glyph(glyph: Glyph, templates: dict[str, Glyph]) -> Digit | None:
    """1 つの桁を、最も近いテンプレートの桁にする。決められなければ None。"""
    scored = sorted(
        (
            (float(cv2.matchTemplate(glyph, t, cv2.TM_CCOEFF_NORMED)[0, 0]), name)
            for name, t in templates.items()
        ),
        reverse=True,
    )
    if not scored or scored[0][0] < MIN_SCORE:
        return None
    margin = scored[0][0] - (scored[1][0] if len(scored) > 1 else 0.0)
    if margin < MIN_MARGIN:
        return None
    return Digit(scored[0][1], scored[0][0], margin)


def read_number(
    image: Image,
    rect: Rect,
    templates: dict[str, Glyph] | None = None,
    min_height: int = MIN_GLYPH_H,
) -> int | None:
    """領域の数(0 以上の整数)を読む。桁が無い、読めない桁がある、テンプレートが無いときは None。"""
    templates = templates if templates is not None else load_templates()
    glyphs = segment_glyphs(image, rect, min_height)
    if not glyphs or not templates:
        return None
    digits = [classify_glyph(g, templates) for g in glyphs]
    if any(d is None for d in digits):
        return None
    return int("".join(d.value for d in digits if d is not None))
