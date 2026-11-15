"""盤・拡大盤・建設画面の移動(vision/navigation.py)のテスト。

実機の画面(datasets/eval/monopoly/screens/、Git 管理外)を、偽の入出力で返す。タップに応じて画面が変わる。
画像が無い環境では飛ばす。
"""

from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import pytest
from numpy.typing import NDArray

from bglm.core.models import Frame, InputAction, Point, Tap
from bglm.plugins.monopoly.vision import navigation as nav
from bglm.plugins.monopoly.vision.executor import CONFIRM_YES, Driver
from bglm.plugins.monopoly.vision.ownership import HELP_DISMISS, ZOOM_ENTRY, ZOOM_RETURN

SCREENS = Path("datasets/eval/monopoly/screens")


def load(name: str) -> NDArray[np.uint8]:
    path = SCREENS / f"{name}.png"
    if not path.exists():
        pytest.skip(f"実機の画面が無い: {path}")
    return np.asarray(cv2.imread(str(path)), dtype=np.uint8)


class ReactiveIo:
    """最初の画面から始め、決めた位置のタップで画面が変わる。決めていない位置のタップは、何も起こらない。"""

    def __init__(self, start: NDArray[np.uint8], reactions: dict[Point, NDArray[np.uint8]]) -> None:
        self.current = start
        self.reactions = reactions
        self.taps: list[Point] = []

    def capture(self) -> Frame:
        return Frame.from_image(self.current, datetime(2026, 11, 11))

    def perform(self, action: InputAction) -> None:
        assert isinstance(action, Tap)
        self.taps.append(action.at)
        if action.at in self.reactions:
            self.current = self.reactions[action.at]


def driver(io: ReactiveIo) -> Driver:
    return Driver(io=io, sleep=lambda _s: None)


def test_return_on_the_board_sends_nothing() -> None:
    io = ReactiveIo(load("my_turn_end_turn"), {})
    assert nav.return_to_board(driver(io))
    assert io.taps == []


def test_return_from_the_zoomed_board_presses_return_once() -> None:
    board = load("my_turn_end_turn")
    io = ReactiveIo(load("zoomed_board"), {ZOOM_RETURN: board})
    assert nav.return_to_board(driver(io))
    assert io.taps == [ZOOM_RETURN]


def test_return_closes_a_notice_with_ok() -> None:
    board = load("my_turn_end_turn")
    io = ReactiveIo(load("ok_dialog_maxed"), {nav.NOTICE_OK: load("improvements")})
    io.reactions[ZOOM_RETURN] = board
    assert nav.return_to_board(driver(io))
    assert io.taps == [nav.NOTICE_OK, ZOOM_RETURN]


def test_return_that_never_reaches_the_board_gives_up() -> None:
    io = ReactiveIo(load("zoomed_board"), {})  # 押しても変わらない
    assert not nav.return_to_board(driver(io))
    assert io.taps == [ZOOM_RETURN] * nav.RETURN_TRIES


def test_trade_screen_is_closed_only_when_asked() -> None:
    board = load("my_turn_end_turn")
    trade = load("trade_ai_offer")
    closing = ReactiveIo(trade, {CONFIRM_YES: board})
    assert nav.return_to_board(driver(closing), close_trade=True)
    assert closing.taps == [nav.TRADE_CANCEL, CONFIRM_YES]

    # 指定しないときは、取引の Cancel を押さない(AI の提案を断る操作と紛れさせない)
    other = ReactiveIo(trade, {})
    assert not nav.return_to_board(driver(other))
    assert nav.TRADE_CANCEL not in other.taps


def test_abnormal_color_is_not_a_successful_return_when_checked() -> None:
    # 端末の色補正のように、全体の色を変える
    dark = (load("my_turn_end_turn") * 0.6).astype(np.uint8)
    assert nav.return_to_board(driver(ReactiveIo(dark, {})))
    assert not nav.return_to_board(driver(ReactiveIo(dark, {})), check_color=True)


def test_open_group_dismisses_the_help_and_returns_the_image() -> None:
    zoomed = load("zoomed_board")
    io = ReactiveIo(load("my_turn_end_turn"), {ZOOM_ENTRY["pink"]: zoomed})
    opened = nav.open_group(driver(io), "pink")
    assert opened.problem == "" and opened.screen == "zoomed_board"
    assert opened.image is zoomed or np.array_equal(opened.image, zoomed)
    assert io.taps == [ZOOM_ENTRY["pink"], HELP_DISMISS]


def test_open_group_does_not_press_the_help_on_an_unexpected_screen() -> None:
    io = ReactiveIo(load("my_turn_end_turn"), {})  # 押しても、盤のまま
    opened = nav.open_group(driver(io), "pink")
    assert opened.problem and io.taps == [ZOOM_ENTRY["pink"]]


def test_open_group_wanting_only_the_building_screen_refuses_the_zoomed_board() -> None:
    # 組を全部持っていないと拡大盤が開く。案内を消すタップは、拡大盤の上の別の場所を押しかねないので送らない
    io = ReactiveIo(load("my_turn_end_turn"), {ZOOM_ENTRY["pink"]: load("zoomed_board")})
    opened = nav.open_group(driver(io), "pink", want=("improvements",))
    assert opened.problem and opened.screen == "zoomed_board"
    assert io.taps == [ZOOM_ENTRY["pink"]]


def test_open_group_closes_a_notice_raised_by_the_help_tap() -> None:
    improvements = load("improvements")
    io = ReactiveIo(
        load("my_turn_end_turn"),
        {ZOOM_ENTRY["pink"]: improvements, HELP_DISMISS: load("ok_dialog_maxed")},
    )
    io.reactions[nav.NOTICE_OK] = improvements
    log: list[str] = []
    d = Driver(io=io, sleep=lambda _s: None, log=log)
    opened = nav.open_group(d, "pink")
    assert opened.problem == "" and opened.screen == "improvements"
    assert io.taps == [ZOOM_ENTRY["pink"], HELP_DISMISS, nav.NOTICE_OK]
    assert any("通知" in line for line in log)
