"""実行ループ(runtime.py)のテスト。実機の画面の見本と、偽の OCR・偽の入出力で、画面ごとの動きを確かめる。

画面の見本は datasets/eval/monopoly/(Git 管理外)。無い環境では、該当のテストを飛ばす。
"""

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import pytest
from numpy.typing import NDArray

from bglm.core.models import Frame, InputAction, Tap
from bglm.plugins.monopoly import runtime as rt
from bglm.plugins.monopoly.logic.decisions import Decider
from bglm.plugins.monopoly.logic.log_replay import PositionTracker
from bglm.plugins.monopoly.logic.models import MonopolyState, Player
from bglm.plugins.monopoly.vision import dialog_reader as dr
from bglm.plugins.monopoly.vision import executor as ex
from bglm.plugins.monopoly.vision.log_reader import OcrLine
from bglm.plugins.monopoly.vision.ownership import ZOOM_RETURN

SELF, AI = Player.SELF, Player.AI
SCREENS = Path("datasets/eval/monopoly/screens")
FLOW = Path("datasets/eval/monopoly/roll_flow")


def load(directory: Path, name: str) -> NDArray[np.uint8]:
    path = directory / f"{name}.png"
    if not path.exists():
        pytest.skip(f"実機の画面が無い: {path}")
    image = cv2.imread(str(path))
    assert image is not None
    return np.asarray(image, dtype=np.uint8)


class ScriptedIo:
    """画面の列を返す。操作のたびに次の画面へ進む(capture では進まない)。操作を記録する。"""

    def __init__(self, frames: Sequence[NDArray[np.uint8]]) -> None:
        self._frames = list(frames)
        self.index = 0
        self.actions: list[InputAction] = []

    def capture(self) -> Frame:
        image = self._frames[min(self.index, len(self._frames) - 1)]
        return Frame.from_image(image, datetime(2026, 11, 7))

    def perform(self, action: InputAction) -> None:
        self.actions.append(action)
        self.index += 1


class NoLogOcr:
    def read(self, image: NDArray[np.uint8]) -> list[OcrLine]:
        return []


class FakeBoxOcr:
    def __init__(
        self, by_box: dict[tuple[int, int, int, int], list[dr.OcrText]] | None = None
    ) -> None:
        self._by_box = by_box or {}

    def read_box(
        self, image: NDArray[np.uint8], box: tuple[int, int, int, int]
    ) -> list[dr.OcrText]:
        return self._by_box.get(box, [])


def agent(
    frames: Sequence[NDArray[np.uint8]],
    box_ocr: FakeBoxOcr | None = None,
    cash: tuple[int, int] = (751, 100),
) -> tuple[rt.Agent, ScriptedIo]:
    io = ScriptedIo(frames)
    driver = ex.Driver(io=io, sleep=lambda _s: None)
    state = MonopolyState(cash={SELF: cash[0], AI: cash[1]})
    a = rt.Agent(
        driver=driver,
        decider=Decider(),
        log_ocr=NoLogOcr(),
        box_ocr=box_ocr or FakeBoxOcr(),
        positions=PositionTracker({SELF: 0, AI: 0}),
        state=state,
    )
    return a, io


def t(text: str, conf: float = 0.97) -> dr.OcrText:
    return dr.OcrText(text, conf)


def auction_ocr(highest: str, ai_cash: str) -> FakeBoxOcr:
    return FakeBoxOcr(
        {
            dr.AUCTION_BID_BOX: [t("Highest bid:")],
            dr.AUCTION_BID_AMOUNT_BOX: [t(highest)],
            dr.AUCTION_CASH_BOX: [t("M751"), t(ai_cash)],
        }
    )


# --- 止まる条件 ---


def test_unknown_screen_waits_without_sending_input() -> None:
    a, io = agent([np.zeros((1080, 2432, 3), dtype=np.uint8)])
    result = rt.step(a)
    assert result.outcome is rt.Outcome.WAITED and io.actions == []


@pytest.mark.parametrize(
    ("name", "needle"),
    [
        ("main_menu", "メインメニュー"),
        ("bid_keypad", "キーパッド"),
        ("jail_bail_confirm", "刑務所"),
        ("buy_confirm", "確認ダイアログ"),
    ],
)
def test_screens_that_need_a_human_stop_and_send_nothing(name: str, needle: str) -> None:
    a, io = agent([load(SCREENS, name)])
    result = rt.step(a)
    assert result.outcome is rt.Outcome.STOPPED
    assert needle in result.reason
    assert io.actions == []


def test_tinted_board_stops_before_anything_is_sent() -> None:
    board = load(SCREENS, "my_turn_end_turn").copy()
    board[..., 0] = np.clip(board[..., 0].astype(np.int16) + 8, 0, 255).astype(np.uint8)
    board[..., 2] = np.clip(board[..., 2].astype(np.int16) - 47, 0, 255).astype(np.uint8)
    a, io = agent([board])
    result = rt.step(a)
    assert result.outcome is rt.Outcome.STOPPED and "色" in result.reason
    assert io.actions == []


def test_pause_screen_is_resumed_without_touching_other_buttons() -> None:
    a, io = agent([load(SCREENS, "pause"), load(SCREENS, "my_turn_end_turn")])
    result = rt.step(a)
    assert result.outcome is rt.Outcome.ACTED and result.action == "resume_from_pause"
    assert io.actions == [Tap(rt.PAUSE_RESUME)]


def test_improvements_screen_is_returned_from() -> None:
    a, io = agent([load(SCREENS, "improvements"), load(SCREENS, "zoomed_board")])
    result = rt.step(a)
    assert result.outcome is rt.Outcome.ACTED and result.action == "return_from_improvements"
    assert io.actions == [Tap(ZOOM_RETURN)]


def test_open_log_is_closed() -> None:
    from bglm.plugins.monopoly.vision.log_reader import LOG_CLOSE

    a, io = agent([load(SCREENS, "log_open"), load(SCREENS, "my_turn_end_turn")])
    result = rt.step(a)
    assert result.outcome is rt.Outcome.ACTED and result.action == "close_log"
    assert io.actions == [Tap(LOG_CLOSE)]


def test_zoomed_board_is_returned_to_the_board() -> None:
    a, io = agent([load(SCREENS, "zoomed_board"), load(SCREENS, "my_turn_end_turn")])
    result = rt.step(a)
    assert result.outcome is rt.Outcome.ACTED and result.action == "return_from_zoom"
    assert io.actions == [Tap(ZOOM_RETURN)]


# --- 動く画面 ---


def test_end_turn_screen_taps_end_turn() -> None:
    a, io = agent([load(SCREENS, "my_turn_end_turn"), load(SCREENS, "ai_turn_banner")])
    result = rt.step(a)
    assert result.outcome is rt.Outcome.ACTED and result.action == "end_turn"
    assert io.actions == [Tap(ex.END_TURN)]


def test_card_dialog_is_closed() -> None:
    a, io = agent([load(FLOW, "card_dialog"), load(FLOW, "my_roll_done")])
    result = rt.step(a)
    assert result.outcome is rt.Outcome.ACTED and result.action == "close_card"
    assert io.actions == [Tap(ex.CARD_CLOSE)]


def test_purchase_that_the_policy_wants_is_bought() -> None:
    # Kentucky Avenue(220)。方針の価値が価格を上回る。購入画面、Buy、確認、Yes の順
    ocr = FakeBoxOcr({dr.PURCHASE_BOX: [t('Purchase "Kentucky Avenue" for M220?')]})
    frames = [load(SCREENS, "buy_dialog"), load(SCREENS, "buy_confirm"), load(SCREENS, "after_buy")]
    a, io = agent(frames, ocr, cash=(751, 600))
    result = rt.step(a)
    assert result.outcome is rt.Outcome.ACTED and result.action == "buy Kentucky Avenue"
    assert io.actions == [Tap(ex.BUY), Tap(ex.CONFIRM_YES)]


def test_purchase_the_policy_does_not_want_is_passed() -> None:
    # Water Works(150)。方針の価値が価格を下回る。Pass、確認、Yes の後にオークション
    ocr = FakeBoxOcr({dr.PURCHASE_BOX: [t('Purchase "Water Works" for M150?')]})
    frames = [load(SCREENS, "buy_dialog"), load(SCREENS, "pass_confirm"), load(SCREENS, "auction")]
    a, io = agent(frames, ocr)
    result = rt.step(a)
    assert result.outcome is rt.Outcome.ACTED and result.action == "pass Water Works"
    assert io.actions == [Tap(ex.PASS), Tap(ex.CONFIRM_YES)]


def test_purchase_that_cannot_be_afforded_is_passed() -> None:
    ocr = FakeBoxOcr({dr.PURCHASE_BOX: [t('Purchase "Park Place" for M350?')]})
    frames = [load(SCREENS, "buy_dialog"), load(SCREENS, "pass_confirm"), load(SCREENS, "auction")]
    a, io = agent(frames, ocr, cash=(140, 98))
    result = rt.step(a)
    assert result.action.startswith("pass Park Place")
    assert io.actions[0] == Tap(ex.PASS)


def test_unreadable_purchase_never_buys() -> None:
    a, io = agent([load(SCREENS, "buy_dialog")], FakeBoxOcr())  # OCR が何も読めない
    result = rt.step(a)
    assert result.outcome is rt.Outcome.STOPPED and "読めない" in result.reason
    assert io.actions == []


def test_auction_bids_the_opponents_cash() -> None:
    # 実機: Water Works のオークション。最高入札 44、Dog の現金 100。100 と同額で入札する(土地は、見送った直後の記録)
    auction = load(SCREENS, "auction")
    keypad = load(SCREENS, "bid_keypad")
    board = load(SCREENS, "after_buy")
    a, io = agent([auction, keypad, keypad, keypad, keypad, board], auction_ocr("44", "M100"))
    a.current_auction = "Water Works"
    result = rt.step(a)
    assert result.outcome is rt.Outcome.ACTED and result.action == "bid 100 Water Works"
    assert io.actions == [
        Tap(ex.BID),
        Tap(ex.KEYPAD_DIGITS["1"]),
        Tap(ex.KEYPAD_DIGITS["0"]),
        Tap(ex.KEYPAD_DIGITS["0"]),
        Tap(ex.KEYPAD_ACCEPT),
    ]


def test_auction_without_a_known_square_stops() -> None:
    a, io = agent([load(SCREENS, "auction")], auction_ocr("44", "M100"))  # Log に見送りの行が無い
    result = rt.step(a)
    assert result.outcome is rt.Outcome.STOPPED and "土地が分からない" in result.reason
    assert io.actions == []


def test_auction_with_unreadable_bid_stops_and_never_bids() -> None:
    ocr = FakeBoxOcr({dr.AUCTION_CASH_BOX: [t("M751"), t("M100")]})  # 枠を読めない
    a, io = agent([load(SCREENS, "auction")], ocr)
    result = rt.step(a)
    assert result.outcome is rt.Outcome.STOPPED and "最高入札額" in result.reason
    assert io.actions == []


def test_auction_beyond_the_limit_forfeits_after_confirming() -> None:
    # 最高入札が方針の上限(Water Works は 150)を超えていれば、降りる(Forfeit → Yes)
    a, io = agent(
        [load(SCREENS, "auction"), load(SCREENS, "forfeit_confirm"), load(SCREENS, "after_buy")],
        auction_ocr("400", "M1500"),
        cash=(751, 1500),
    )
    a.current_auction = "Water Works"
    result = rt.step(a)
    assert result.outcome is rt.Outcome.ACTED and result.action == "forfeit Water Works"
    assert io.actions == [Tap(ex.FORFEIT), Tap(ex.CONFIRM_YES)]


def test_ai_trade_offer_is_declined() -> None:
    frames = [
        load(SCREENS, "trade_ai_offer"),
        load(SCREENS, "trade_cancel_confirm"),
        load(SCREENS, "after_buy"),
    ]
    a, io = agent(frames)
    result = rt.step(a)
    assert result.outcome is rt.Outcome.ACTED and result.action.startswith("decline trade")
    assert io.actions == [Tap(ex.TRADE_DECLINE), Tap(ex.CONFIRM_YES)]


# --- 外側のループ ---


def test_run_stops_when_the_screen_stays_unknown() -> None:
    a, _ = agent([np.zeros((1080, 2432, 3), dtype=np.uint8)])
    result = rt.run(a, max_steps=1000)
    assert result.outcome is rt.Outcome.STOPPED and "分からない状態" in result.reason


def test_run_stops_at_the_first_screen_that_needs_a_human() -> None:
    a, io = agent([load(SCREENS, "main_menu")])
    result = rt.run(a)
    assert result.outcome is rt.Outcome.STOPPED and result.screen == "main_menu"
    assert io.actions == []


def test_own_build_mortgage_and_sale_are_applied_to_the_state_and_their_log_lines_are_dropped() -> (
    None
):
    from bglm.plugins.monopoly.logic import events as ev
    from bglm.plugins.monopoly.logic.models import Holding

    a, _ = agent([np.zeros((1080, 2432, 3), dtype=np.uint8)], cash=(1000, 500))
    a.state = MonopolyState(
        cash={SELF: 1000, AI: 500},
        holdings={
            "Baltic Avenue": Holding(owner=SELF),
            "Mediterranean Avenue": Holding(owner=SELF),
            "Reading Railroad": Holding(owner=SELF),
        },
    )
    rt._apply_own_action(a, "build", {"Baltic Avenue": 1})
    assert a.state.cash[SELF] == 950 and a.state.holdings["Baltic Avenue"].houses == 1
    rt._apply_own_action(a, "mortgage", {"Reading Railroad": 1})
    assert a.state.cash[SELF] == 950 + 100 and a.state.holdings["Reading Railroad"].mortgaged
    rt._apply_own_action(a, "sell", {"Baltic Avenue": 1})
    assert a.state.holdings["Baltic Avenue"].houses == 0
    lines: list[ev.LogEvent] = [
        ev.HousesBuilt(SELF, 1, "Baltic Avenue"),
        ev.Mortgaged(SELF, "Reading Railroad", 100),
        ev.HousesBuilt(AI, 1, "Vermont Avenue"),
    ]
    assert rt.own_action_events(lines) == [ev.HousesBuilt(AI, 1, "Vermont Avenue")]


def test_debt_menu_is_recognised_and_stops_when_no_funding_step_is_left() -> None:
    a, io = agent([load(SCREENS, "debt_menu_auto_sell")])
    a.state = MonopolyState(cash={SELF: -679, AI: 806}, holdings={})
    result = rt.step(a)
    assert result.outcome is rt.Outcome.STOPPED and "Resign" in result.reason
    assert io.actions == []  # Auto Sell と Resign は、自動では押さない


def test_game_statistics_returns_to_the_main_menu_and_stops() -> None:
    a, io = agent([load(SCREENS, "game_statistics_after_resign"), load(SCREENS, "main_menu")])
    result = rt.step(a)
    assert result.outcome is rt.Outcome.STOPPED and result.action == "game_over"
    assert io.actions == [Tap(rt.STATS_MAIN_MENU)]


def test_bid_above_the_cash_on_screen_is_never_sent() -> None:
    from bglm.plugins.monopoly.logic.opponent_model import BidModel

    class FixedBid:
        bid_model = BidModel()

        def auction_bid(
            self, live: object, square: str, highest_bid: int, first: bool = True
        ) -> int:
            return 800

    a, io = agent([load(SCREENS, "auction")], auction_ocr("44", "M100"), cash=(751, 100))
    a.current_auction = "Water Works"
    a.decider = FixedBid()  # type: ignore[assignment]
    # 画面の自分の現金は M751(auction_ocr)。それを超える入札は、送らない
    result = rt.step(a)
    assert result.outcome is rt.Outcome.STOPPED and "超える" in result.reason
    assert io.actions == []


def test_auction_cash_misread_with_a_leading_four_is_matched_to_the_ledger() -> None:
    # 実機: 自分の現金 ₼56 が「A456」と読まれ、₼456 持つと誤認して、₼197 を入札した
    ocr = FakeBoxOcr(
        {
            dr.AUCTION_BID_BOX: [t("Highest bid:")],
            dr.AUCTION_BID_AMOUNT_BOX: [],
            dr.AUCTION_CASH_BOX: [t("A456"), t("M197")],
        }
    )
    a, io = agent([load(SCREENS, "auction")], ocr, cash=(56, 197))
    a.current_auction = "Pennsylvania Railroad"
    result = rt.step(a)
    assert (
        not any(isinstance(x, Tap) and x == Tap(ex.BID) for x in io.actions)
        or result.outcome is rt.Outcome.ACTED
    )
    assert "197" not in result.action  # 現金 56 で、197 は入札しない


def test_notice_dialog_is_dismissed_with_ok() -> None:
    a, io = agent([load(SCREENS, "ok_dialog_maxed"), load(SCREENS, "my_turn_end_turn")])
    result = rt.step(a)
    assert result.outcome is rt.Outcome.ACTED and result.action == "dismiss_notice"
    assert io.actions == [Tap(rt.NOTICE_OK)]


class CountingIo(ScriptedIo):
    """capture の回数を数える(実機では、1 枚 約 2 秒かかる)。"""

    def __init__(self, frames: Sequence[NDArray[np.uint8]]) -> None:
        super().__init__(frames)
        self.captures = 0

    def capture(self) -> Frame:
        self.captures += 1
        return super().capture()


def test_unreadable_purchase_dialog_stops_after_a_single_capture() -> None:
    # 判別の 1 枚で、土地名・価格も読む(読み取りのために取り直さない)
    io = CountingIo([load(SCREENS, "buy_dialog")])
    a, _ = agent([load(SCREENS, "buy_dialog")], FakeBoxOcr())  # OCR が何も読めない
    a.driver = ex.Driver(io=io, sleep=lambda _s: None)
    result = rt.step(a)
    assert result.outcome is rt.Outcome.STOPPED
    assert io.captures == 1


# --- 建設は End Turn の直前(Roll の前ではない) ---

PINK = ("St. Charles Place", "States Avenue", "Virginia Avenue")


def pink_agent(frames: Sequence[NDArray[np.uint8]]) -> tuple[rt.Agent, ScriptedIo]:
    from bglm.plugins.monopoly.logic.models import Holding

    a, io = agent(frames, cash=(1500, 500))
    a.state = MonopolyState(
        cash={SELF: 1500, AI: 500}, holdings={n: Holding(owner=SELF) for n in PINK}
    )
    a.positions = PositionTracker({SELF: 0, AI: 4})  # 相手は、ピンクの手前 7 マス
    return a, io


def record_builds(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, int]]]:
    from bglm.core.models import ExecutionResult

    calls: list[tuple[str, dict[str, int]]] = []

    def fake(driver: ex.Driver, group: str, plan: dict[str, int]) -> ExecutionResult:
        calls.append((group, dict(plan)))
        return ExecutionResult(success=True)

    monkeypatch.setattr(rt.builder, "build_group", fake)
    return calls


def test_the_policy_builds_just_before_end_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = record_builds(monkeypatch)
    a, _io = pink_agent([load(SCREENS, "my_turn_end_turn")])
    result = rt.step(a)
    assert result.outcome is rt.Outcome.ACTED and result.action.startswith("build pink")
    assert calls and calls[0][0] == "pink"
    assert sum(a.state.holdings[n].houses for n in PINK) > 0  # 操作の結果が、状態に反映される


def test_nothing_is_built_before_the_roll(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = record_builds(monkeypatch)
    a, _io = pink_agent([load(SCREENS, "my_turn_roll")])
    rt.step(a)  # Roll を送る(反映されず止まっても、ここでは問わない)
    assert calls == []


def test_a_highest_bid_above_my_last_bid_is_recorded_as_the_opponents_bid() -> None:
    a, _io = agent([load(SCREENS, "auction")], auction_ocr("44", "M100"), cash=(751, 100))
    a.current_auction = "Water Works"  # 定価 150
    rt.step(a)
    assert a.decider.bid_model.ai_bids == [44 / 150]


def test_my_own_last_bid_is_not_recorded_as_the_opponents() -> None:
    a, _io = agent([load(SCREENS, "auction")], auction_ocr("44", "M100"), cash=(751, 100))
    a.current_auction = "Water Works"
    a.last_bid = 44  # 画面の最高入札額 44 は、自分の入札
    rt.step(a)
    assert a.decider.bid_model.ai_bids == []
