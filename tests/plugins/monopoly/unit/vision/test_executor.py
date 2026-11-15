"""Monopoly の executor(vision/executor.py)のテスト。実機の代わりに、画面の列を返す偽物で確かめる。

画面は参照画像(datasets/eval/monopoly/screens/、Git 管理外)を使う。無い環境ではテストを飛ばす。
期待する操作の並びは、COORDINATES.md の値と一致させる。
"""

from collections.abc import Sequence
from pathlib import Path

import cv2
import numpy as np
import pytest

from bglm.core.models import Frame, HoldDrag, InputAction, Tap
from bglm.plugins.monopoly.vision import executor as ex

EVAL = Path("datasets/eval/monopoly/screens")


def load(name: str) -> np.ndarray:
    path = EVAL / name
    if not path.exists():
        pytest.skip(f"参照画像が無い: {path}")
    image = cv2.imread(str(path))
    assert image is not None
    return np.asarray(image, dtype=np.uint8)


class FakeIo:
    """画面の列を順に返し、送られた入力を記録する。列の最後の画面は繰り返す。"""

    def __init__(self, screens: Sequence[np.ndarray]) -> None:
        self._screens = list(screens)
        self._index = 0
        self.actions: list[InputAction] = []

    def capture(self) -> Frame:
        image = self._screens[min(self._index, len(self._screens) - 1)]
        return Frame.from_image(image, __import__("datetime").datetime(2026, 11, 2))

    def perform(self, action: InputAction) -> None:
        self.actions.append(action)
        self._index += 1


def driver(screens: Sequence[np.ndarray]) -> tuple[ex.Driver, FakeIo, list[float]]:
    io = FakeIo(screens)
    waits: list[float] = []
    return ex.Driver(io=io, sleep=waits.append), io, waits


def test_roll_waits_then_holds_and_moves_up() -> None:
    roll_screen = load("my_turn_roll.png")
    end_screen = load("my_turn_end_turn.png")
    d, io, waits = driver([roll_screen, end_screen])

    result = ex.roll(d)

    assert result.success
    assert io.actions == [HoldDrag(ex.ROLL_FROM, ex.ROLL_TO, 600, 6, 40)]
    assert waits[0] == ex.ROLL_SETTLE_SEC


def test_roll_refuses_when_not_on_roll_screen_and_sends_nothing() -> None:
    d, io, _ = driver([load("my_turn_end_turn.png")])

    result = ex.roll(d)

    assert not result.success
    assert io.actions == []


def test_roll_retries_once_then_fails_when_unchanged() -> None:
    roll_screen = load("my_turn_roll.png")
    d, io, _ = driver([roll_screen])

    result = ex.roll(d)

    assert not result.success
    assert len(io.actions) == ex.UNCHANGED_LIMIT


def test_end_turn_taps_end_turn_button_and_checks_change() -> None:
    d, io, _ = driver([load("my_turn_end_turn.png"), load("my_turn_roll.png")])

    result = ex.end_turn(d)

    assert result.success
    assert io.actions == [Tap(ex.END_TURN)]


def test_end_turn_refuses_on_roll_screen() -> None:
    d, io, _ = driver([load("my_turn_roll.png")])

    result = ex.end_turn(d)

    assert not result.success
    assert io.actions == []


def test_cancel_trade_taps_cancel_then_confirms_yes() -> None:
    # Cancel の確認(「取引をキャンセルしますか」)は、確認ダイアログ(confirm_dialog)として判別する
    trade = load("trade.png")
    confirm = load("trade_cancel_confirm.png")
    board = load("my_turn_end_turn.png")
    d, io, _ = driver([trade, confirm, board])

    result = ex.cancel_trade(d)

    assert result.success
    assert io.actions == [Tap(ex.TRADE_CANCEL), Tap(ex.TRADE_CANCEL_YES)]


def test_pay_bail_refuses_on_board_screen() -> None:
    d, io, _ = driver([load("my_turn_end_turn.png")])

    result = ex.pay_bail(d)

    assert not result.success
    assert io.actions == []


FLOW = Path("datasets/eval/monopoly/roll_flow")


def load_flow(name: str) -> np.ndarray:
    path = FLOW / name
    if not path.exists():
        pytest.skip(f"実機の画面が無い: {path}")
    image = cv2.imread(str(path))
    assert image is not None
    return np.asarray(image, dtype=np.uint8)


def test_close_card_taps_the_close_button_once_when_it_closes() -> None:
    d, io, _ = driver([load_flow("card_dialog.png"), load_flow("my_roll_done.png")])

    result = ex.close_card(d)

    assert result.success
    assert io.actions == [Tap(ex.CARD_CLOSE)]


def test_close_card_retries_then_fails_when_the_card_stays() -> None:
    card = load_flow("card_dialog.png")
    d, io, _ = driver([card])

    result = ex.close_card(d)

    assert not result.success
    assert io.actions == [Tap(ex.CARD_CLOSE)] * ex.UNCHANGED_LIMIT


def test_close_card_refuses_when_no_card_is_shown_and_sends_nothing() -> None:
    d, io, _ = driver([load_flow("my_roll_done.png")])

    result = ex.close_card(d)

    assert not result.success
    assert io.actions == []


# --- 確定操作(購入、見送り、Forfeit、取引の応答、入札) ---


def test_buy_taps_buy_then_yes_after_the_confirm_dialog_appears() -> None:
    d, io, _ = driver([load("buy_dialog.png"), load("buy_confirm.png"), load("after_buy.png")])

    result = ex.buy(d)

    assert result.success
    assert io.actions == [Tap(ex.BUY), Tap(ex.CONFIRM_YES)]


def test_buy_does_not_press_yes_when_no_confirm_dialog_appears() -> None:
    # Buy を押しても確認が出ない(押し直しても同じ)。Yes の位置は、押さない
    d, io, _ = driver([load("buy_dialog.png")])

    result = ex.buy(d)

    assert not result.success
    assert io.actions == [Tap(ex.BUY)] * ex.UNCHANGED_LIMIT
    assert Tap(ex.CONFIRM_YES) not in io.actions


def test_buy_refuses_on_the_wrong_screen_and_sends_nothing() -> None:
    d, io, _ = driver([load("my_turn_end_turn.png")])

    assert not ex.buy(d).success
    assert io.actions == []


def test_pass_on_purchase_leads_to_the_auction() -> None:
    d, io, _ = driver([load("buy_dialog.png"), load("pass_confirm.png"), load("auction.png")])

    result = ex.pass_on_purchase(d)

    assert result.success
    assert io.actions == [Tap(ex.PASS), Tap(ex.CONFIRM_YES)]


def test_forfeit_taps_forfeit_then_yes() -> None:
    d, io, _ = driver([load("auction.png"), load("forfeit_confirm.png"), load("after_buy.png")])

    result = ex.forfeit(d)

    assert result.success
    assert io.actions == [Tap(ex.FORFEIT), Tap(ex.CONFIRM_YES)]


def test_decline_trade_confirms_yes() -> None:
    d, io, _ = driver(
        [load("trade_ai_offer.png"), load("trade_cancel_confirm.png"), load("after_buy.png")]
    )

    result = ex.respond_to_trade(d, accept=False)

    assert result.success
    assert io.actions == [Tap(ex.TRADE_DECLINE), Tap(ex.CONFIRM_YES)]


def test_accept_trade_taps_accept_and_succeeds_when_the_board_returns() -> None:
    d, io, _ = driver([load("trade_ai_offer.png"), load("after_buy.png")])

    result = ex.respond_to_trade(d, accept=True)

    assert result.success
    assert io.actions == [Tap(ex.TRADE_ACCEPT)]


def test_accept_trade_confirms_when_a_confirm_dialog_appears() -> None:
    d, io, _ = driver([load("trade_ai_offer.png"), load("buy_confirm.png"), load("after_buy.png")])

    result = ex.respond_to_trade(d, accept=True)

    assert result.success
    assert io.actions == [Tap(ex.TRADE_ACCEPT), Tap(ex.CONFIRM_YES)]


def test_accept_trade_outside_the_trade_screen_sends_nothing() -> None:
    d, io, _ = driver([load("after_buy.png")])

    result = ex.respond_to_trade(d, accept=True)

    assert not result.success and io.actions == []


def test_bid_enters_digits_one_by_one_then_accepts() -> None:
    auction, keypad, board = load("auction.png"), load("bid_keypad.png"), load("after_buy.png")
    # Bid の後はキーパッド。数字ごとにキーパッドを確かめる。ACCEPT の後に盤へ
    d, io, _ = driver([auction, keypad, keypad, keypad, board])

    result = ex.bid(d, 65)

    assert result.success
    assert io.actions == [
        Tap(ex.BID),
        Tap(ex.KEYPAD_DIGITS["6"]),
        Tap(ex.KEYPAD_DIGITS["5"]),
        Tap(ex.KEYPAD_ACCEPT),
    ]


def test_bid_stops_if_the_keypad_closes_after_a_digit() -> None:
    auction, keypad = load("auction.png"), load("bid_keypad.png")
    d, io, _ = driver([auction, keypad, auction])  # 1 桁目の後に、キーパッドが閉じた

    result = ex.bid(d, 65)

    assert not result.success
    assert Tap(ex.KEYPAD_ACCEPT) not in io.actions  # ACCEPT は押さない(誤入札を確定しない)


def test_bid_refuses_amounts_out_of_range() -> None:
    d, io, _ = driver([load("auction.png")])

    assert not ex.bid(d, 0).success
    assert not ex.bid(d, 1000).success
    assert io.actions == []
