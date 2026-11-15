"""`N/M`(未配置の団員 / 使える団員)の数字の読み取り。

白い箱の中の濃い文字を、連結成分で3つ(N、/、M)に分け、24x36 に正規化して、テンプレートと比べる。
テンプレートは scripts/maquis/build_templates.py が、記録した実画面から作る(0〜4。5 は実機で見ていないので無い。
読めない文字は None を返し、呼び出し側が止まる)。
"""

from functools import cache
from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray

from bglm.toolkit.components import connected_components
from bglm.toolkit.images import gray, load_image

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "data" / "templates" / "digits"
GLYPH_SIZE = (24, 36)  # 幅, 高さ
DARK_MAX = 110  # 文字の濃さ(グレースケール)
MIN_AREA = 40  # これ未満の成分は汚れとみなす
MATCH_MIN = 0.80  # 正規化した2値画像の一致率の下限
MARGIN_MIN = 0.05  # 1位と2位の一致率の差の下限


def glyph_mask(box_image: NDArray[np.uint8]) -> NDArray[np.uint8]:
    """箱の中の濃い画素(文字)を 1 にした画像。"""
    return np.asarray(gray(box_image) < DARK_MAX, dtype=np.uint8)


def split_glyphs(mask: NDArray[np.uint8]) -> list[NDArray[np.uint8]]:
    """文字ごとに切り出した2値画像(左から右)。小さな汚れは除く。"""
    components, labels = connected_components(mask)
    found = sorted((c for c in components if c.area >= MIN_AREA), key=lambda c: c.x)
    out: list[NDArray[np.uint8]] = []
    for c in found:
        box = labels[c.y : c.y + c.height, c.x : c.x + c.width]
        out.append(np.asarray(box == c.label, dtype=np.uint8))
    return out


def normalize_glyph(glyph: NDArray[np.uint8]) -> NDArray[np.uint8]:
    """文字を、縦横比を保たず 24x36 に伸ばした 0/255 の画像にする(「1」と「/」の細さの違いは形で残る)。"""
    resized = cv2.resize(glyph * 255, GLYPH_SIZE, interpolation=cv2.INTER_AREA)
    return np.asarray(np.where(resized >= 127, 255, 0), dtype=np.uint8)


@cache
def templates() -> dict[str, NDArray[np.uint8]]:
    found: dict[str, NDArray[np.uint8]] = {}
    for path in sorted(TEMPLATE_DIR.glob("*.png")):
        image = load_image(path, cv2.IMREAD_GRAYSCALE)
        if image is not None:
            found[path.stem] = image
    return found


def classify_glyph(glyph: NDArray[np.uint8]) -> tuple[str | None, float]:
    """文字の種類("0"〜"4"、"slash")と確信度。読めなければ (None, 確信度)。"""
    target = normalize_glyph(glyph)
    scores = sorted(
        ((float(np.mean(target == t)), key) for key, t in templates().items()), reverse=True
    )
    if not scores:
        return None, 0.0
    best, key = scores[0]
    second = scores[1][0] if len(scores) > 1 else 0.0
    if best < MATCH_MIN or best - second < MARGIN_MIN:
        return None, best
    return key, best


def read_agent_counts(box_image: NDArray[np.uint8]) -> tuple[tuple[int, int] | None, float]:
    """「N/M」を (N, M) に読む。読めなければ (None, 確信度)。"""
    glyphs = split_glyphs(glyph_mask(box_image))
    if len(glyphs) != 3:
        return None, 0.0
    read = [classify_glyph(g) for g in glyphs]
    confidence = min(score for _, score in read)
    keys = [key for key, _ in read]
    if keys[1] != "slash" or keys[0] in (None, "slash") or keys[2] in (None, "slash"):
        return None, confidence
    return (int(str(keys[0])), int(str(keys[2]))), confidence
