"""Monopoly の所持金の読み取り。座標は原寸(2432x1080)。

画面上部中央の 2 つのパネル(左が自分、右が AI)に「₼ + 数字」が出る。手番の側のパネルは明るく、
文字は暗い。手番でない側は暗く、文字は明るい(極性が反転する)。パネルの左端は、画像ごとに数 px ずれる。
そこで、領域の背景(メディアン)との差で、暗い文字と明るい文字の 2 つのマスクを作り、
₼ の記号が見つかったほうの極性を採る。₼ より右の連結成分を、1 桁ずつテンプレートで読む。

読めないとき(₼ が無い、桁が想定外、一致度が低い)は、値を埋めずに不明(value=None)を返す。
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray

from bglm.core.protocols import GameIo
from bglm.toolkit.components import connected_components
from bglm.toolkit.images import load_image
from bglm.toolkit.template_reader import TemplateReader

DIGIT_DIR = Path(__file__).resolve().parent.parent / "data" / "digits"
YEN_DIR = Path(__file__).resolve().parent.parent / "data" / "yen"

ROW_Y = (28, 60)  # 文字が入る行(原寸)
SELF_X = (1115, 1265)  # 自分のパネルの文字の探索範囲
AI_X = (1295, 1445)
TEXT_MAX_X = 110  # 範囲の左端からこの位置より右は、パネルの縁・別の絵なので見ない

BACKGROUND_KERNEL = 15  # メディアンの大きさ。文字(幅 約11px)より大きく、パネルの勾配より小さい
CONTRAST_MIN = 25  # 背景との差の下限(輝度)。暗い文字・明るい文字の両方に使う
MIN_AREA = 3  # この画素数未満の連結成分は雑音
YEN_WIDTH = (15, 20)  # ₼ の幅
YEN_MIN_HEIGHT = 10
DIGIT_HEIGHT = (8, 17)
DIGIT_WIDTH = (3, 15)
MINUS_MAX_HEIGHT = 3
MINUS_WIDTH = (5, 8)
MINUS_Y = (6, 10)  # ₼ の上端からの位置
DIGIT_PITCH = 12.5  # 数字 1 つ分の幅(つながった成分を分ける数の見積もり)
MAX_GAP = 8  # 隣り合う文字の間の隙間の上限
MAX_DIGITS = 5  # 6 桁以上は、領域に収まらない。収まらない値は読まない
GLYPH_SIZE = (16, 20)  # 正規化した 1 文字の大きさ(幅, 高さ)
YEN_SIZE = (24, 20)  # 正規化した ₼ の大きさ
YEN_MATCH_MIN = 0.80  # ₼ の一致度の下限。つながった 2 桁を ₼ と取り違えないための確認

MATCH_MIN = 0.75  # 桁の一致度の下限。評価で根拠を決める(RESULT.md)


@dataclass(frozen=True)
class CashReading:
    value: int | None  # 不明なら None
    confidence: float  # 桁の一致度の最小値。不明なら 0.0


UNKNOWN = CashReading(None, 0.0)


@dataclass(frozen=True)
class CashPair:
    me: CashReading
    ai: CashReading


@dataclass(frozen=True)
class Glyphs:
    """1 つの領域から切り出した文字。digits は左から順。"""

    polarity: str  # "dark" か "light"
    negative: bool
    yen: NDArray[np.uint8]  # 正規化した ₼
    digits: tuple[NDArray[np.uint8], ...]  # 正規化した 1 桁ずつ(0/255)


def _components(mask: NDArray[np.uint8]) -> list[tuple[int, int, int, int]]:
    found = [
        (c.x, c.y, c.width, c.height)
        for c in connected_components(mask)[0]
        if c.area >= MIN_AREA and c.x < TEXT_MAX_X
    ]
    return sorted(found)


def _normalize(
    mask: NDArray[np.uint8],
    box: tuple[int, int, int, int],
    size: tuple[int, int] = GLYPH_SIZE,
) -> NDArray[np.uint8]:
    x, y, w, h = box
    canvas = np.zeros((size[1], size[0]), dtype=np.uint8)
    cut = mask[y : y + h, x : x + w]
    left = (size[0] - w) // 2
    canvas[:h, left : left + w] = cut
    return canvas


def _split_merged(
    mask: NDArray[np.uint8], box: tuple[int, int, int, int]
) -> list[tuple[int, int, int, int]]:
    """つながった数字を、列ごとの画素数が最も少ない位置で分ける。"""
    x, y, w, h = box
    count = max(2, round(w / DIGIT_PITCH))
    columns = (mask[y : y + h, x : x + w] > 0).sum(axis=0)
    cuts = [0]
    for k in range(1, count):
        centre = round(k * w / count)
        lo, hi = max(cuts[-1] + 3, centre - 3), min(w - 3, centre + 3)
        if lo > hi:
            return []
        cuts.append(lo + int(np.argmin(columns[lo : hi + 1])))
    cuts.append(w)
    parts = []
    for left, right in zip(cuts, cuts[1:], strict=False):
        ink = np.nonzero(columns[left:right])[0]
        if ink.size == 0:
            return []
        parts.append((x + left + int(ink[0]), y, int(ink[-1] - ink[0] + 1), h))
    return parts


def _parse(mask: NDArray[np.uint8], polarity: str, verify_yen: bool) -> Glyphs | None:
    boxes = _components(mask)
    yen = next(
        (b for b in boxes if YEN_WIDTH[0] <= b[2] <= YEN_WIDTH[1] and b[3] >= YEN_MIN_HEIGHT),
        None,
    )
    if yen is None:
        return None
    yen_glyph = _normalize(mask, yen, YEN_SIZE)
    if verify_yen and _yen_reader().read(yen_glyph).confidence < YEN_MATCH_MIN:
        return None
    end = yen[0] + yen[2]
    negative = False
    digits: list[tuple[int, int, int, int]] = []
    for b in boxes:
        if b[0] < end or b is yen:
            continue  # ₼ より左、または直前の文字に重なる小片は雑音
        if not digits and not negative and _is_minus(b, yen):
            negative = True
        elif DIGIT_HEIGHT[0] <= b[3] <= DIGIT_HEIGHT[1] and b[2] >= DIGIT_WIDTH[0]:
            if b[0] - end > MAX_GAP:
                return None  # 数字の途中が欠けた可能性。後ろの桁を捨てて読まない
            if b[2] <= DIGIT_WIDTH[1]:
                digits.append(b)
            else:
                parts = _split_merged(mask, b)
                if not parts:
                    return None
                digits.extend(parts)
        elif b[3] >= DIGIT_HEIGHT[0]:
            break  # 想定外の大きな成分
        else:
            continue  # 小さな雑音
        end = b[0] + b[2]
    if not 1 <= len(digits) <= MAX_DIGITS:
        return None
    return Glyphs(polarity, negative, yen_glyph, tuple(_normalize(mask, b) for b in digits))


def _is_minus(box: tuple[int, int, int, int], yen: tuple[int, int, int, int]) -> bool:
    return (
        MINUS_WIDTH[0] <= box[2] <= MINUS_WIDTH[1]
        and box[3] <= MINUS_MAX_HEIGHT
        and yen[1] + MINUS_Y[0] <= box[1] <= yen[1] + MINUS_Y[1]
        and box[0] - (yen[0] + yen[2]) <= MAX_GAP
    )


def extract_glyphs(
    image: NDArray[np.uint8], x_range: tuple[int, int], verify_yen: bool = True
) -> Glyphs | None:
    """領域から ₼ と数字を切り出す。極性は、₼ が見つかったほうを採る(両方なら桁数の多いほう)。"""
    gray = cv2.cvtColor(image[ROW_Y[0] : ROW_Y[1], x_range[0] : x_range[1]], cv2.COLOR_BGR2GRAY)
    background = cv2.medianBlur(gray, BACKGROUND_KERNEL).astype(np.float32)
    diff = gray.astype(np.float32) - background
    candidates = [
        glyphs
        for polarity, mask in (("dark", diff < -CONTRAST_MIN), ("light", diff > CONTRAST_MIN))
        if (glyphs := _parse(mask.astype(np.uint8), polarity, verify_yen)) is not None
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda g: len(g.digits), reverse=True)
    if len(candidates) == 2 and len(candidates[0].digits) == len(candidates[1].digits):
        return None  # 極性が決められない
    return candidates[0]


def _load(directory: Path) -> TemplateReader:
    templates: dict[str, list[NDArray[np.uint8]]] = {}
    for path in sorted(directory.glob("*.png")):
        image = load_image(path, cv2.IMREAD_GRAYSCALE)
        if image is not None:
            templates.setdefault(path.name[0], []).append(image)
    return TemplateReader(templates)


@cache
def _reader() -> TemplateReader:
    return _load(DIGIT_DIR)


@cache
def _yen_reader() -> TemplateReader:
    return _load(YEN_DIR)


def read_glyphs(glyphs: Glyphs | None, reader: TemplateReader | None = None) -> CashReading:
    if glyphs is None:
        return UNKNOWN
    reader = reader or _reader()
    text = ""
    confidence = 1.0
    for glyph in glyphs.digits:
        reading = reader.read(glyph)
        if reading.confidence < MATCH_MIN:
            return UNKNOWN
        text += reading.value
        confidence = min(confidence, reading.confidence)
    value = int(text)
    return CashReading(-value if glyphs.negative else value, confidence)


def read_cash(image: NDArray[np.uint8]) -> CashPair:
    """画面(原寸 BGR)から、自分と AI の所持金を読む。"""
    return CashPair(
        read_glyphs(extract_glyphs(image, SELF_X)),
        read_glyphs(extract_glyphs(image, AI_X)),
    )


def read_cash_stable(
    io: GameIo, interval: float = 0.5, sleep: Callable[[float], None] = time.sleep
) -> CashPair:
    """間隔を置いた画面を最大 3 枚読み、同じ値が 2 回出たものだけを採る(更新途中の表示を避ける)。

    一致が出なければ不明。画面の表示が遅れて更新される場合は、待っても解決しないことがある。
    それは、この関数ではなく、出来事から予測した所持金との照合(状態の追跡)で検出する。
    """
    reads: list[CashPair] = []
    for attempt in range(3):
        if attempt:
            sleep(interval)
        reads.append(read_cash(io.capture().image))
        if (
            attempt >= 1
            and _agree(reads[-1].me, reads[-2].me)
            and _agree(reads[-1].ai, reads[-2].ai)
        ):
            return CashPair(_merge(reads[-1].me, reads[-2].me), _merge(reads[-1].ai, reads[-2].ai))
    return CashPair(_vote([r.me for r in reads]), _vote([r.ai for r in reads]))


def _agree(a: CashReading, b: CashReading) -> bool:
    return a.value is not None and a.value == b.value


def _merge(a: CashReading, b: CashReading) -> CashReading:
    return CashReading(a.value, min(a.confidence, b.confidence))


def _vote(readings: list[CashReading]) -> CashReading:
    values = [r.value for r in readings if r.value is not None]
    for value in set(values):
        if values.count(value) >= 2:
            matching = [r.confidence for r in readings if r.value == value]
            return CashReading(value, min(matching))
    return UNKNOWN
