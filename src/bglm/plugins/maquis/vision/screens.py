"""Maquis の画面の種類の判別。座標は原寸(2432x1080)。

盤の通常の画面、終局のダイアログ、ターン終了の確認、山札の画面、タイトルを分ける。どれにも当たらない画面
(ルール、設定、一時停止メニューなど)は UNKNOWN。推測で別の画面にしない(`CLAUDE.md`)。

終局のダイアログは、中央に「もう一度遊ぶ」「メインメニュー」「完全版を入手」の3つの帯が縦に並ぶ。
**「完全版を入手」は購入に移るので、決して押さない**(layout.END_FORBIDDEN)。
"""

from enum import Enum
from functools import cache
from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray

from bglm.plugins.maquis.vision import layout
from bglm.plugins.maquis.vision.counters import PhaseIcon, read_phase
from bglm.toolkit.images import crop, gray, load_image
from bglm.toolkit.screen import has_size

SCREEN_DIR = Path(__file__).resolve().parent.parent / "data" / "templates" / "screens"
CREAM_MIN = 0.6  # 帯・ボタンが「クリーム色」の割合の下限
MATCH_MIN = 0.90  # テンプレートとの相関の下限
TITLE_BOX = (429, 391, 933, 960)  # メインメニューのボタン列


class ScreenKind(Enum):
    BOARD = "board"
    END_DEFEAT = "end_defeat"  # 「レジスタンス壊滅」
    END_OTHER = "end_other"  # 終局のダイアログで、壊滅ではないもの(勝ち・引き分けの画面は未観測)
    CONFIRM = "confirm"  # 「ターンを終了しますか?」
    DECK = "deck"  # 巡回カードの画面
    TITLE = "title"
    UNKNOWN = "unknown"


@cache
def _template(name: str) -> NDArray[np.uint8] | None:
    return load_image(SCREEN_DIR / f"{name}.png", cv2.IMREAD_GRAYSCALE)


def _cream_fraction(image: NDArray[np.uint8], box: tuple[int, int, int, int]) -> float:
    patch = crop(image, box).astype(int)
    b, g, r = patch[..., 0], patch[..., 1], patch[..., 2]
    return float(np.mean((r > 235) & (g > 225) & (b > 190)))


def _correlation(image: NDArray[np.uint8], box: tuple[int, int, int, int], name: str) -> float:
    ref = _template(name)
    if ref is None:
        return 0.0
    patch = cv2.resize(gray(crop(image, box)), None, fx=0.5, fy=0.5)
    if patch.shape != ref.shape:
        return 0.0
    return float(cv2.matchTemplate(patch, ref, cv2.TM_CCOEFF_NORMED)[0, 0])


def _end_dialog(image: NDArray[np.uint8]) -> bool:
    """中央に、タイトルの帯と、縦に並ぶ2つの帯(もう一度遊ぶ、メインメニュー)がある。"""
    return (
        _cream_fraction(image, (600, 95, 1800, 175)) >= CREAM_MIN
        and _cream_fraction(image, (1000, 420, 1500, 495)) >= CREAM_MIN
        and _cream_fraction(image, (1000, 585, 1500, 655)) >= CREAM_MIN
    )


def classify_screen(image: NDArray[np.uint8]) -> ScreenKind:
    if not has_size(image, layout.SCREEN_SIZE):
        return ScreenKind.UNKNOWN
    # 山札の画面もパネルがクリーム色なので、終局より先に見出しで判別する
    if _correlation(image, layout.END_TITLE_BOX, "deck_title") >= MATCH_MIN:
        return ScreenKind.DECK
    if _end_dialog(image):
        if _correlation(image, layout.END_TITLE_BOX, "end_defeat") >= MATCH_MIN:
            return ScreenKind.END_DEFEAT
        return ScreenKind.END_OTHER
    if _correlation(image, TITLE_BOX, "title_menu") >= MATCH_MIN:
        return ScreenKind.TITLE
    if _correlation(image, layout.CONFIRM_BOX, "confirm_dialog") >= MATCH_MIN:
        return ScreenKind.CONFIRM
    icon, _ = read_phase(image)
    if icon in (PhaseIcon.BICYCLE, PhaseIcon.FLAG):
        return ScreenKind.BOARD
    return ScreenKind.UNKNOWN
