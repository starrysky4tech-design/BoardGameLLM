"""購入画面・オークション画面の文字の読み取り(vision/dialog_reader.py)のテスト。

偽の OCR で、整形・補正・安全側の動きを確かめる(常に動く)。実機の画面の読み取りは、本物の OCR で確かめる
(画面が無い環境では飛ばす)。
"""

from pathlib import Path

import cv2
import numpy as np
import pytest
from numpy.typing import NDArray

from bglm.plugins.monopoly.vision import dialog_reader as dr

BLANK = np.zeros((1080, 2432, 3), dtype=np.uint8)
EVAL = Path("datasets/eval/monopoly/screens")


class FakeOcr:
    def __init__(self, by_box: dict[tuple[int, int, int, int], list[dr.OcrText]]) -> None:
        self._by_box = by_box

    def read_box(
        self, image: NDArray[np.uint8], box: tuple[int, int, int, int]
    ) -> list[dr.OcrText]:
        return self._by_box.get(box, [])


def t(text: str, conf: float = 0.97) -> dr.OcrText:
    return dr.OcrText(text, conf)


def test_purchase_is_read_with_square_and_price() -> None:
    ocr = FakeOcr({dr.PURCHASE_BOX: [t('Purchase "Pennsylvania Avenue" for M320?')]})
    assert dr.read_purchase(BLANK, ocr) == dr.PurchaseOffer("Pennsylvania Avenue", 320)


def test_purchase_repairs_ocr_confusions() -> None:
    ocr = FakeOcr({dr.PURCHASE_BOX: [t('Purchase "lllinois Avenue" for M240?')]})  # I → l
    assert dr.read_purchase(BLANK, ocr) == dr.PurchaseOffer("Illinois Avenue", 240)


def test_purchase_with_low_confidence_or_unknown_square_is_none() -> None:
    assert (
        dr.read_purchase(
            BLANK, FakeOcr({dr.PURCHASE_BOX: [t('Purchase "Boardwalk" for M400?', 0.5)]})
        )
        is None
    )
    assert (
        dr.read_purchase(
            BLANK, FakeOcr({dr.PURCHASE_BOX: [t('Purchase "Nowhere Street" for M10?')]})
        )
        is None
    )
    assert dr.read_purchase(BLANK, FakeOcr({})) is None


def test_auction_reads_bid_and_both_cash_amounts() -> None:
    ocr = FakeOcr(
        {
            dr.AUCTION_BID_BOX: [t("Highest bid:"), t("M15")],
            dr.AUCTION_BID_AMOUNT_BOX: [t("15")],
            dr.AUCTION_CASH_BOX: [t("M1040"), t("M30")],
        }
    )
    view = dr.read_auction(BLANK, ocr)
    assert (view.highest_bid, view.cash_self, view.cash_ai) == (15, 1040, 30)


def test_auction_with_no_bid_yet_is_zero_and_unreadable_frame_is_none() -> None:
    no_bid = FakeOcr(
        {dr.AUCTION_BID_BOX: [t("Highest bid:")], dr.AUCTION_CASH_BOX: [t("M500"), t("M100")]}
    )
    assert dr.read_auction(BLANK, no_bid).highest_bid == 0
    # 黄色い枠は出ているのに、文字を読めない: 0 とはしない(読めていない)
    framed = BLANK.copy()
    x0, y0, x1, y1 = dr.AUCTION_BID_BOX
    framed[y0:y1, x0:x1] = (40, 230, 250)  # BGR の黄色
    unreadable = FakeOcr({dr.AUCTION_CASH_BOX: [t("M500"), t("M100")]})
    assert dr.read_auction(framed, unreadable).highest_bid is None
    # 黄色い枠そのものが出ない = まだ誰も入札していない(実機 2026-11-07)
    assert dr.read_auction(BLANK, unreadable).highest_bid == 0


def test_auction_cash_missing_is_none_not_zero() -> None:
    ocr = FakeOcr({dr.AUCTION_BID_BOX: [t("Highest bid:")], dr.AUCTION_CASH_BOX: [t("M500")]})
    view = dr.read_auction(BLANK, ocr)
    assert view.cash_self == 500 and view.cash_ai is None


@pytest.fixture(scope="module")
def real_ocr() -> dr.BoxOcr:
    return dr.BoxOcr()


def _load(name: str) -> NDArray[np.uint8]:
    path = EVAL / f"{name}.png"
    if not path.exists():
        pytest.skip(f"実機の画面が無い: {path}")
    image = cv2.imread(str(path))
    assert image is not None
    return np.asarray(image, dtype=np.uint8)


def test_real_purchase_screen(real_ocr: dr.BoxOcr) -> None:
    assert dr.read_purchase(_load("buy_dialog"), real_ocr) == dr.PurchaseOffer(
        "Virginia Avenue", 160
    )
    # 買う確認(BUY PROPERTY)が重なった画面でも、背後の購入文を読める(旧見本)
    assert dr.read_purchase(_load("buy_confirm_old"), real_ocr) == dr.PurchaseOffer(
        "Pennsylvania Avenue", 320
    )


def test_real_auction_screen(real_ocr: dr.BoxOcr) -> None:
    view = dr.read_auction(_load("auction"), real_ocr)
    assert view.cash_self == 1040 and view.cash_ai == 30
    assert view.highest_bid == 15


def test_low_confidence_amount_is_unreadable_not_zero() -> None:
    # 実機で起きた誤り: 金額 M15 を信頼度 0.78 で読み、捨てて、「入札なし(0)」と取り違えた
    ocr = FakeOcr(
        {dr.AUCTION_BID_BOX: [t("Highest bid:", 0.99)], dr.AUCTION_BID_AMOUNT_BOX: [t("15", 0.6)]}
    )
    assert dr.read_auction(BLANK, ocr).highest_bid is None
