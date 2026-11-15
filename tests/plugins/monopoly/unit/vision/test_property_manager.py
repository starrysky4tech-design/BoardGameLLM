"""土地の管理(抵当・解除・家の売却)の操作のテスト。実機の画面の見本(Git 管理外)と、偽の入出力で、順序を確かめる。"""

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import pytest
from numpy.typing import NDArray

from bglm.core.models import Frame, InputAction, Tap
from bglm.plugins.monopoly.vision import executor as ex
from bglm.plugins.monopoly.vision import property_manager as pm
from bglm.plugins.monopoly.vision.dialog_reader import OcrText
from bglm.plugins.monopoly.vision.ownership import HELP_DISMISS, ZOOM_ENTRY, ZOOM_RETURN, ZOOM_TILE

SCREENS = Path("datasets/eval/monopoly/screens")


def load(name: str) -> NDArray[np.uint8]:
    path = SCREENS / f"{name}.png"
    if not path.exists():
        pytest.skip(f"実機の画面が無い: {path}")
    image = cv2.imread(str(path))
    assert image is not None
    return np.asarray(image, dtype=np.uint8)


class ScriptedIo:
    """操作のたびに、次の画面へ進む(取得では進まない)。"""

    def __init__(self, frames: Sequence[NDArray[np.uint8]]) -> None:
        self._frames = list(frames)
        self.index = 0
        self.actions: list[InputAction] = []

    def capture(self) -> Frame:
        return Frame.from_image(
            self._frames[min(self.index, len(self._frames) - 1)], datetime(2026, 11, 8)
        )

    def perform(self, action: InputAction) -> None:
        self.actions.append(action)
        self.index += 1


class ConfirmOcr:
    """確認ダイアログの本文の枠で、決めた文を返す偽の OCR。"""

    def __init__(self, text: str, label: str = "Mortgage") -> None:
        self._text = text
        self._label = label

    def read_box(self, image: object, box: tuple[int, int, int, int]) -> list[OcrText]:
        if box == pm.ACTION_LABEL_BOX:
            return [OcrText(self._label, 0.99)]
        return [OcrText(self._text, 0.95)] if self._text else []


def driver(frames: Sequence[NDArray[np.uint8]]) -> tuple[ex.Driver, ScriptedIo]:
    io = ScriptedIo(frames)
    return ex.Driver(io=io, sleep=lambda _s: None), io


def test_mortgage_flow_opens_the_detail_confirms_and_returns() -> None:
    board, zoomed = load("my_turn_end_turn"), load("zoomed_board")
    d, io = driver(
        [
            board,  # 開始
            zoomed,  # 色グループを押した後
            zoomed,  # 案内を消した後
            load("manage_property_mine"),  # 土地を押した後(詳細)
            load("mortgage_confirm"),  # Mortgage を押した後
            load("zoomed_after_mortgage"),  # Yes の後
            board,  # Return の後
        ]
    )
    result = pm.mortgage(
        d, "Baltic Avenue", ConfirmOcr("Are you sure you want to mortgage Baltic Avenue for M30?")
    )
    assert result.success, result.reason
    assert io.actions == [
        Tap(ZOOM_ENTRY["brown"]),
        Tap(HELP_DISMISS),
        Tap(ZOOM_TILE["Baltic Avenue"]),
        Tap(pm.DETAIL_ACTION),
        Tap(ex.CONFIRM_YES),
        Tap(ZOOM_RETURN),
    ]


def test_mortgage_does_not_press_yes_when_no_confirm_dialog_appears() -> None:
    board, zoomed = load("my_turn_end_turn"), load("zoomed_board")
    d, io = driver(
        [board, zoomed, zoomed, load("manage_property_mine"), load("manage_property_mine"), board]
    )
    result = pm.mortgage(d, "Baltic Avenue", ConfirmOcr(""))
    assert not result.success
    assert Tap(ex.CONFIRM_YES) not in io.actions


def test_mortgage_outside_the_board_sends_nothing() -> None:
    d, io = driver([load("main_menu")])
    assert not pm.mortgage(d, "Baltic Avenue", ConfirmOcr("")).success and io.actions == []


def test_sell_houses_refuses_an_unregistered_group() -> None:
    d, io = driver([load("my_turn_end_turn")])
    assert not pm.sell_houses(d, "yellow", {"Marvin Gardens": 1}).success and io.actions == []


def test_mortgage_cancels_with_no_when_the_dialog_is_an_unmortgage() -> None:
    board, zoomed = load("my_turn_end_turn"), load("zoomed_board")
    d, io = driver(
        [
            board,
            zoomed,
            zoomed,
            load("manage_property_mortgaged"),
            load("unmortgage_confirm"),
            zoomed,
            board,
        ]
    )
    result = pm.mortgage(
        d, "Baltic Avenue", ConfirmOcr("Are you sure you want to unmortgage Baltic Avenue for M33?")
    )
    assert not result.success and "取り消した" in (result.reason or "")
    assert Tap(pm.CONFIRM_NO) in io.actions and Tap(ex.CONFIRM_YES) not in io.actions


def test_confirm_text_matching() -> None:
    assert pm.confirm_text_matches(
        "Are you sure you want to mortgage Baltic Avenue for M30?", "Baltic Avenue", True
    )
    assert not pm.confirm_text_matches(
        "Are you sure you want to unmortgage Baltic Avenue for M33?", "Baltic Avenue", True
    )
    assert pm.confirm_text_matches(
        "Are you sure you want to unmortgage Baltic Avenue for M33?", "Baltic Avenue", False
    )
    assert not pm.confirm_text_matches("", "Baltic Avenue", True)


def test_every_catalogue_deed_has_a_position_and_a_color_group() -> None:
    from bglm.plugins.monopoly.logic.catalogue import CATALOGUE
    from bglm.plugins.monopoly.vision.ownership import PROPERTY_GROUP, ZOOM_TILE

    missing = [n for n in CATALOGUE if n not in PROPERTY_GROUP or n not in ZOOM_TILE]
    assert missing == []


def test_confirm_text_accepts_the_screen_spelling_of_the_railroad() -> None:
    assert pm.confirm_text_matches(
        "Are you sure you want to mortgage B. & O. Railroad for M100?", "B&O Railroad", True
    )
    assert not pm.confirm_text_matches(
        "Are you sure you want to mortgage Reading Railroad for M100?", "B&O Railroad", True
    )


def test_confirm_text_tolerates_l_for_i() -> None:
    assert pm.confirm_text_matches(
        "Are you sure you want to mortgage lllinois Avenue for M120?", "Illinois Avenue", True
    )


def test_reading_from_the_tiles_own_group_view_wins_over_an_edge_reading() -> None:
    from bglm.plugins.monopoly.vision import bars
    from bglm.plugins.monopoly.vision.holdings import HoldingsResult, _convert, merge_view
    from bglm.plugins.monopoly.vision.ownership import Owner

    result = HoldingsResult()
    edge = {
        "St. James Place": bars.PropertyReading(Owner.ME, 0, False)
    }  # ピンクの画面の端(家の数が不正確)
    own = {"St. James Place": bars.PropertyReading(Owner.ME, 2, False)}
    merge_view(result, "pink", edge, _convert)
    merge_view(result, "improvements_orange", own, _convert)
    assert result.problems == [] and result.readings["St. James Place"].houses == 2  # type: ignore[union-attr]


def test_already_mortgaged_is_not_pressed_and_reported() -> None:
    board, zoomed = load("my_turn_end_turn"), load("zoomed_board")
    d, io = driver([board, zoomed, zoomed, load("manage_property_mortgaged"), zoomed, board])
    result = pm.mortgage(d, "Baltic Avenue", ConfirmOcr("", label="Unmortgage"))
    assert not result.success and "すでに抵当済み" in (result.reason or "")
    assert Tap(pm.DETAIL_ACTION) not in io.actions and Tap(ex.CONFIRM_YES) not in io.actions
