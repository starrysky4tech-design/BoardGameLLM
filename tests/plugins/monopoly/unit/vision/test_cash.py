"""所持金の読み取りの単体テスト。合成画像(テンプレートの数字を並べた画像)で、桁の分割と不明の経路を確かめる。

期待値は、並べた数字から手で書く。実機の画像での精度は scripts/monopoly/eval_cash.py で評価する(RESULT.md)。
"""

from datetime import datetime
from pathlib import Path
from typing import cast

import cv2
import numpy as np
import pytest
from numpy.typing import NDArray

from bglm.core.models import Frame
from bglm.core.protocols import GameIo
from bglm.plugins.monopoly.vision.cash import (
    AI_X,
    DIGIT_DIR,
    ROW_Y,
    SELF_X,
    YEN_DIR,
    CashReading,
    extract_glyphs,
    read_cash,
    read_cash_stable,
)

PANEL = 170  # 手番の側のパネル(明るい)
INK = 60  # 暗い文字
TOP = 6  # 行の中での ₼ の上端


def _glyph(char: str, variant: int = 0) -> NDArray[np.uint8]:
    image = cv2.imread(str(DIGIT_DIR / f"{char}_{variant}.png"), cv2.IMREAD_GRAYSCALE)
    assert image is not None
    ys, xs = np.nonzero(image)
    return image[: ys.max() + 1, xs.min() : xs.max() + 1]


def _yen() -> NDArray[np.uint8]:
    """暗い文字用の ₼(背が高いほう)。"""
    best = None
    for path in sorted(YEN_DIR.glob("*.png")):
        image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        assert image is not None
        ys, xs = np.nonzero(image)
        cut = image[: ys.max() + 1, xs.min() : xs.max() + 1]
        if best is None or cut.shape[0] > best.shape[0]:
            best = cut
    assert best is not None
    return best


def _blank() -> NDArray[np.uint8]:
    return np.full((1080, 2432, 3), PANEL, dtype=np.uint8)


def _draw(
    image: NDArray[np.uint8],
    x_range: tuple[int, int],
    digits: str,
    *,
    yen: bool = True,
    minus: bool = False,
    gap: int = 2,
) -> None:
    x = x_range[0] + 20
    y0 = ROW_Y[0] + TOP
    yen_glyph = _yen()
    if yen:
        region = image[y0 : y0 + yen_glyph.shape[0], x : x + yen_glyph.shape[1]]
        region[yen_glyph > 0] = INK
    x += yen_glyph.shape[1] + 2
    if minus:
        image[y0 + 8 : y0 + 10, x : x + 6] = INK
        x += 6 + gap
    for char in digits:
        glyph = _glyph(char)
        h, w = glyph.shape
        region = image[y0 : y0 + h, x : x + w]
        region[glyph > 0] = INK
        x += w + gap


def test_reads_four_digits_on_both_panels() -> None:
    image = _blank()
    _draw(image, SELF_X, "1500")
    _draw(image, AI_X, "260")
    pair = read_cash(image)
    assert pair.me.value == 1500
    assert pair.ai.value == 260
    assert pair.me.confidence > 0.9


def test_reads_negative_value() -> None:
    image = _blank()
    _draw(image, SELF_X, "23", minus=True)
    assert read_cash(image).me.value == -23


def test_reading_is_stable_across_calls() -> None:
    image = _blank()
    _draw(image, SELF_X, "828")
    assert read_cash(image) == read_cash(image)


def test_unknown_without_yen_symbol() -> None:
    image = _blank()
    _draw(image, SELF_X, "1500", yen=False)
    assert read_cash(image).me == CashReading(None, 0.0)
    assert extract_glyphs(image, SELF_X) is None


def test_unknown_when_blank() -> None:
    pair = read_cash(_blank())
    assert pair.me.value is None
    assert pair.ai.value is None


def test_unknown_when_too_many_digits() -> None:
    image = _blank()
    _draw(image, SELF_X, "1234567")
    assert read_cash(image).me.value is None


def test_unknown_when_digit_is_noise() -> None:
    image = _blank()
    _draw(image, SELF_X, "15")
    x = SELF_X[0] + 20 + _yen().shape[1] + 2 + 30
    image[ROW_Y[0] + TOP : ROW_Y[0] + TOP + 14, x : x + 8] = INK  # 形のない塊
    assert read_cash(image).me.value is None


@pytest.mark.parametrize("digits", ["1500", "828", "37"])
def test_touching_digits_are_split(digits: str) -> None:
    image = _blank()
    _draw(image, AI_X, digits, gap=0)
    assert read_cash(image).ai.value in (
        int(digits),
        None,
    )  # つながって読めなければ不明。誤読は不可


def test_templates_exist_for_every_digit() -> None:
    names = {Path(p).name[0] for p in DIGIT_DIR.glob("*.png")}
    assert names >= set("0123456789")


class _FakeIo:
    """用意した画面を、順に返す。"""

    def __init__(self, images: list[NDArray[np.uint8]]) -> None:
        self._images = images
        self.calls = 0

    def capture(self) -> Frame:
        image = self._images[min(self.calls, len(self._images) - 1)]
        self.calls += 1
        return Frame.from_image(image, datetime(2026, 11, 2))


def _scene(me: str, ai: str) -> NDArray[np.uint8]:
    image = _blank()
    _draw(image, SELF_X, me)
    _draw(image, AI_X, ai)
    return image


def test_stable_read_accepts_two_matching_frames() -> None:
    io = _FakeIo([_scene("1500", "260"), _scene("1500", "260")])
    pair = read_cash_stable(cast(GameIo, io), sleep=lambda _: None)
    assert (pair.me.value, pair.ai.value) == (1500, 260)
    assert io.calls == 2


def test_stable_read_rejects_value_that_changes_every_frame() -> None:
    io = _FakeIo([_scene("1500", "260"), _scene("1440", "260"), _scene("1380", "260")])
    pair = read_cash_stable(cast(GameIo, io), sleep=lambda _: None)
    assert pair.me.value is None
    assert pair.ai.value == 260


def test_stable_read_uses_two_of_three() -> None:
    io = _FakeIo([_scene("1500", "260"), _scene("1440", "260"), _scene("1500", "260")])
    pair = read_cash_stable(cast(GameIo, io), sleep=lambda _: None)
    assert pair.me.value == 1500


# AI のパネル(淡色の文字)の 8 と 4 が、一致度の下限に届かず読めなかった画像(3 局目の「AI の現金が不明」の原因)。
# 値は、画像の数字を目視で確かめた(2026-11-10)。評価画像は Git 管理外なので、無い環境では飛ばす
AI_PANEL_CASES = [
    ("board_scan/board1.png", 38),
    ("cash/D/D_t1_after_roll.png", 81),
    ("dice3/roll14_result.png", 42),
    ("dice3/roll17_check.png", 78),
    ("dice3/roll22_check.png", 40),
    ("screens/after_auto_sell.png", 1875),
]


@pytest.mark.parametrize(("name", "want"), AI_PANEL_CASES, ids=[c[0] for c in AI_PANEL_CASES])
def test_ai_panel_digits_8_and_4_are_read(name: str, want: int) -> None:
    path = Path("datasets/eval/monopoly") / name
    if not path.exists():
        pytest.skip(f"評価画像が無い: {path}")
    image = cv2.imread(str(path))
    assert read_cash(np.asarray(image, dtype=np.uint8)).ai.value == want
