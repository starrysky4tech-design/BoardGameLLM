"""建設の操作(builder.py)のテスト。偽の入出力で、操作の順序と、押さない条件を確かめる。"""

from datetime import datetime

import numpy as np
from numpy.typing import NDArray

from bglm.core.models import Frame, InputAction
from bglm.plugins.monopoly.vision import builder
from bglm.plugins.monopoly.vision import executor as ex


class FixedIo:
    """常に同じ画面を返す(盤の通常の画面でも建設画面でもない、黒い画面)。"""

    def __init__(self, image: NDArray[np.uint8]) -> None:
        self._image = image
        self.actions: list[InputAction] = []

    def capture(self) -> Frame:
        return Frame.from_image(self._image, datetime(2026, 11, 7))

    def perform(self, action: InputAction) -> None:
        self.actions.append(action)


def test_unregistered_group_is_refused_without_input() -> None:
    io = FixedIo(np.zeros((1080, 2432, 3), dtype=np.uint8))
    result = builder.build_group(ex.Driver(io=io, sleep=lambda _s: None), "orange", {"X": 1})
    assert not result.success and io.actions == []


def test_not_on_the_board_sends_nothing() -> None:
    io = FixedIo(np.zeros((1080, 2432, 3), dtype=np.uint8))
    result = builder.build_group(
        ex.Driver(io=io, sleep=lambda _s: None), "pink", {"Virginia Avenue": 1}
    )
    assert not result.success and io.actions == []


def test_plan_outside_the_registered_streets_is_refused() -> None:
    io = FixedIo(np.zeros((1080, 2432, 3), dtype=np.uint8))
    result = builder.build_group(
        ex.Driver(io=io, sleep=lambda _s: None), "pink", {"Baltic Avenue": 1}
    )
    assert not result.success and io.actions == []


def test_group_of_knows_only_calibrated_groups() -> None:
    assert builder.group_of("Virginia Avenue") == "pink"
    assert builder.group_of("Oriental Avenue") == "light_blue"
    assert builder.group_of("Kentucky Avenue") == "red"  # 2026-11-10 に較正
    assert builder.group_of("Boardwalk") == "dark_blue"
    assert builder.group_of("Marvin Gardens") is None  # 黄は未較正


def test_jail_menu_is_a_roll_screen_with_post_bail() -> None:
    import cv2
    import pytest

    from bglm.plugins.monopoly.vision.screens import classify, has_post_bail

    jail = cv2.imread("datasets/eval/monopoly/screens/jail_my_turn_roll.png")
    normal = cv2.imread("datasets/eval/monopoly/screens/my_turn_roll.png")
    if jail is None or normal is None:
        pytest.skip("実機の画面が無い")
    assert classify(jail).name == "board_my_turn_roll" and has_post_bail(jail)
    assert classify(normal).name == "board_my_turn_roll" and not has_post_bail(normal)


def test_ok_notice_dialog_is_recognised() -> None:
    import cv2
    import pytest

    from bglm.plugins.monopoly.vision.screens import classify

    image = cv2.imread("datasets/eval/monopoly/screens/ok_dialog_maxed.png")
    if image is None:
        pytest.skip("実機の画面が無い")
    assert classify(image).name == "ok_dialog"


def test_hotels_on_the_pink_group_are_read() -> None:
    import cv2
    import pytest

    from bglm.plugins.monopoly.vision import bars

    image = cv2.imread("datasets/eval/monopoly/screens/improvements_pink_hotels.png")
    if image is None:
        pytest.skip("実機の画面が無い")
    read = bars.read_buildings(image, bars.VIEWS["improvements_pink"])
    assert [read[n].hotel for n in ("Virginia Avenue", "States Avenue", "St. Charles Place")] == [
        True
    ] * 3


def test_purchase_dialog_with_the_deed_card_is_recognised() -> None:
    import cv2
    import pytest

    from bglm.plugins.monopoly.vision.screens import classify

    image = cv2.imread("datasets/eval/monopoly/screens/buy_dialog_card.png")
    if image is None:
        pytest.skip("実機の画面が無い")
    assert classify(image).name == "buy_dialog"


def test_purchase_text_split_in_two_ocr_pieces_is_joined() -> None:
    from bglm.plugins.monopoly.vision import dialog_reader as dr

    class Split:
        def read_box(self, image: object, box: tuple[int, int, int, int]) -> list[dr.OcrText]:
            return [dr.OcrText("Purchase", 0.99), dr.OcrText(':"Virginia Avenue" for M160?', 0.97)]

    offer = dr.read_purchase(np.zeros((1080, 2432, 3), dtype=np.uint8), Split())  # type: ignore[arg-type]
    assert offer is not None and offer.square == "Virginia Avenue" and offer.price == 160


def test_confirm_over_the_card_purchase_dialog_is_a_confirm_dialog() -> None:
    import cv2
    import pytest

    from bglm.plugins.monopoly.vision.screens import classify

    image = cv2.imread("datasets/eval/monopoly/screens/pass_confirm_over_card.png")
    if image is None:
        pytest.skip("実機の画面が無い")
    assert classify(image).name == "confirm_dialog"


def test_purchase_price_misread_currency_is_accepted_only_when_it_matches_the_list_price() -> None:
    from bglm.plugins.monopoly.vision import dialog_reader as dr

    class Ocr:
        def __init__(self, text: str) -> None:
            self.text = text

        def read_box(self, image: object, box: tuple[int, int, int, int]) -> list[dr.OcrText]:
            return [dr.OcrText("Purchase", 0.99), dr.OcrText(self.text, 0.95)]

    blank = np.zeros((1080, 2432, 3), dtype=np.uint8)
    ok = dr.read_purchase(blank, Ocr('"Boardwalk" for A400?'))  # type: ignore[arg-type]
    assert ok is not None and ok.square == "Boardwalk" and ok.price == 400
    assert dr.read_purchase(blank, Ocr('"Boardwalk" for A4000?')) is None  # type: ignore[arg-type]


def test_auction_cash_with_a_misread_currency_sign() -> None:
    from bglm.plugins.monopoly.vision import dialog_reader as dr

    class Ocr:
        def read_box(self, image: object, box: tuple[int, int, int, int]) -> list[dr.OcrText]:
            if box == dr.AUCTION_CASH_BOX:
                return [dr.OcrText("AA442", 0.95), dr.OcrText("M802", 0.99)]
            return []

    view = dr.read_auction(np.zeros((1080, 2432, 3), dtype=np.uint8), Ocr())  # type: ignore[arg-type]
    assert (view.cash_self, view.cash_ai) == (442, 802)


def test_low_confidence_bid_amount_is_accepted_when_the_frame_reading_agrees() -> None:
    from bglm.plugins.monopoly.vision import dialog_reader as dr

    class Ocr:
        def read_box(self, image: object, box: tuple[int, int, int, int]) -> list[dr.OcrText]:
            if box == dr.AUCTION_BID_BOX:
                return [dr.OcrText("Highest bid:", 0.99), dr.OcrText("M84", 0.97)]
            if box == dr.AUCTION_BID_AMOUNT_BOX:
                return [dr.OcrText("M84", 0.82)]
            return []

    blank = np.zeros((1080, 2432, 3), dtype=np.uint8)
    assert dr.read_auction(blank, Ocr()).highest_bid == 84  # type: ignore[arg-type]

    class Disagree(Ocr):
        def read_box(self, image: object, box: tuple[int, int, int, int]) -> list[dr.OcrText]:
            if box == dr.AUCTION_BID_AMOUNT_BOX:
                return [dr.OcrText("M64", 0.82)]
            return super().read_box(image, box)

    assert dr.read_auction(blank, Disagree()).highest_bid is None  # type: ignore[arg-type]


def test_zoomed_light_blue_owners_and_buildings() -> None:
    import cv2
    import pytest

    from bglm.plugins.monopoly.vision import bars
    from bglm.plugins.monopoly.vision.ownership import Owner

    image = cv2.imread("datasets/eval/monopoly/screens/zoomed_light_blue.png")
    if image is None:
        pytest.skip("実機の画面が無い")
    read = bars.read_view_full(image, bars.VIEWS["light_blue"])
    assert {n: r.owner for n, r in read.items()} == {
        "Connecticut Avenue": Owner.NONE,
        "Vermont Avenue": Owner.AI,
        "Oriental Avenue": Owner.NONE,
        "Reading Railroad": Owner.AI,
        "Baltic Avenue": Owner.ME,
    }
    assert all(r.houses == 0 and not r.hotel for r in read.values())


def test_noisy_auction_cash_digits_are_extracted_for_ledger_matching() -> None:
    from bglm.plugins.monopoly.vision import dialog_reader as dr

    class Ocr:
        def read_box(self, image: object, box: tuple[int, int, int, int]) -> list[dr.OcrText]:
            return [dr.OcrText("M4259", 0.82), dr.OcrText("M.77", 0.78), dr.OcrText("x", 0.2)]

    digits = dr.auction_cash_digits(np.zeros((1080, 2432, 3), dtype=np.uint8), Ocr())  # type: ignore[arg-type]
    assert digits == ["4259", "77"]


def test_trade_offer_is_read_from_the_real_screen() -> None:
    import cv2
    import pytest

    from bglm.plugins.monopoly.logic.models import Trade
    from bglm.plugins.monopoly.vision.dialog_reader import BoxOcr
    from bglm.plugins.monopoly.vision.trade_reader import read_trade_offer

    image = cv2.imread("datasets/eval/monopoly/screens/trade_offer_game2_a.png")
    if image is None:
        pytest.skip("実機の画面が無い")
    assert read_trade_offer(image, BoxOcr()) == Trade(
        proposer_deeds=frozenset({"Oriental Avenue", "Reading Railroad"}),
        proposer_cash=49,
        partner_deeds=frozenset({"Marvin Gardens"}),
        partner_cash=0,
    )


def test_green_improvements_has_no_buildings_yet_and_is_registered_for_building() -> None:
    import cv2
    import pytest

    from bglm.plugins.monopoly.vision import bars, builder

    assert builder.group_of("Pacific Avenue") == "green"
    assert builder.far_first("green")[0] == "Pennsylvania Avenue"  # 入口(Pacific)から最も遠い
    image = cv2.imread("datasets/eval/monopoly/screens/improvements_green.png")
    if image is None:
        pytest.skip("実機の画面が無い")
    read = bars.read_buildings(image, bars.VIEWS["improvements_green"])
    assert all(r.houses == 0 and not r.hotel for r in read.values())


def test_orange_is_registered_and_far_first() -> None:
    from bglm.plugins.monopoly.vision import builder

    assert builder.group_of("St. James Place") == "orange"
    assert builder.far_first("orange") == ["New York Avenue", "Tennessee Avenue", "St. James Place"]


def test_dark_blue_is_registered_and_far_first() -> None:
    from bglm.plugins.monopoly.vision import builder

    assert builder.group_of("Park Place") == "dark_blue"
    assert builder.far_first("dark_blue") == ["Boardwalk", "Park Place"]


def test_red_group_color_band_is_not_read_as_a_hotel() -> None:
    import cv2
    import pytest

    from bglm.plugins.monopoly.vision import bars

    image = cv2.imread("datasets/eval/monopoly/screens/zoomed_red_no_houses.png")
    if image is None:
        pytest.skip("実機の画面が無い")
    read = bars.read_buildings(image, bars.VIEWS["red"])
    assert all(r.houses == 0 and not r.hotel for r in read.values())


def test_bid_amount_with_the_currency_sign_misread_as_four() -> None:
    from bglm.plugins.monopoly.vision import dialog_reader as dr

    class Ocr:
        def __init__(self, frame_text: str, amount_text: str) -> None:
            self.frame_text, self.amount_text = frame_text, amount_text

        def read_box(self, image: object, box: tuple[int, int, int, int]) -> list[dr.OcrText]:
            if box == dr.AUCTION_BID_BOX:
                return [dr.OcrText("Highest bid:", 0.99), dr.OcrText(self.frame_text, 0.90)]
            if box == dr.AUCTION_BID_AMOUNT_BOX:
                return [dr.OcrText(self.amount_text, 0.78)]
            return []

    blank = np.zeros((1080, 2432, 3), dtype=np.uint8)
    # 実機: 「₼40」が枠で「440」、金額枠で「*40」
    assert dr.read_auction(blank, Ocr("440", "*40")).highest_bid == 40  # type: ignore[arg-type]
    # 本当に 440 なら、金額枠も 440 と読む
    assert dr.read_auction(blank, Ocr("440", "*440")).highest_bid == 440  # type: ignore[arg-type]
    # 食い違う読みは、読めなかったことにする
    assert dr.read_auction(blank, Ocr("440", "*60")).highest_bid is None  # type: ignore[arg-type]


def test_bid_with_star_misread_currency_sign_and_low_confidence() -> None:
    from bglm.plugins.monopoly.vision import dialog_reader as dr

    class Ocr:
        def read_box(self, image: object, box: tuple[int, int, int, int]) -> list[dr.OcrText]:
            if box == dr.AUCTION_BID_BOX:
                return [dr.OcrText("Highest bid:", 0.99), dr.OcrText("*420", 0.72)]
            if box == dr.AUCTION_BID_AMOUNT_BOX:
                return [dr.OcrText("*20", 0.77)]
            return []

    assert dr.read_auction(np.zeros((1080, 2432, 3), dtype=np.uint8), Ocr()).highest_bid == 20  # type: ignore[arg-type]
