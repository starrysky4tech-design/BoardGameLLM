"""色グループだけを開いて家の数を読む(vision/holdings.py の `read_group_houses`)のテスト。

実機の画面(datasets/eval/monopoly/screens/、Git 管理外)を、偽の入出力で返す。タップに応じて、盤 → 拡大盤・建設画面
→ 盤と遷移する。開いた回数・タップの並びと、読んだ家の数を確かめる。画像が無い環境では飛ばす。
"""

from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import pytest
from numpy.typing import NDArray

from bglm.core.models import Frame, InputAction, Tap
from bglm.plugins.monopoly.vision.executor import Driver
from bglm.plugins.monopoly.vision.holdings import read_group_houses
from bglm.plugins.monopoly.vision.ownership import HELP_DISMISS, ZOOM_ENTRY, ZOOM_RETURN

SCREENS = Path("datasets/eval/monopoly/screens")
BOARD_FILE = SCREENS / "my_turn_end_turn.png"


def load(name: str) -> NDArray[np.uint8]:
    path = SCREENS / name
    if not path.exists():
        pytest.skip(f"実機の画面が無い: {path}")
    return np.asarray(cv2.imread(str(path)), dtype=np.uint8)


class FakeIo:
    """盤から始め、色グループの位置を押すと、その色グループの画面(opens)に変わる。Return で盤に戻る。"""

    def __init__(self, board: NDArray[np.uint8], opens: dict[str, NDArray[np.uint8]]) -> None:
        self._board = board
        self._opens = {ZOOM_ENTRY[group]: image for group, image in opens.items()}
        self._current = board
        self.taps: list[tuple[int, int]] = []
        self.captures = 0

    def capture(self) -> Frame:
        self.captures += 1
        return Frame.from_image(self._current, datetime(2026, 11, 10))

    def perform(self, action: InputAction) -> None:
        assert isinstance(action, Tap)
        point = action.at
        self.taps.append((point.x, point.y))
        if point in self._opens:
            self._current = self._opens[point]
        elif point == ZOOM_RETURN:
            self._current = self._board


def driver(io: FakeIo) -> Driver:
    return Driver(io=io, sleep=lambda _s: None)


def test_no_groups_opens_nothing() -> None:
    io = FakeIo(load("my_turn_end_turn.png"), {})
    result = read_group_houses(driver(io), ())
    assert result.complete and result.houses == {}
    assert io.taps == [] and io.captures == 1


def test_reads_hotels_in_the_building_screen() -> None:
    io = FakeIo(load("my_turn_end_turn.png"), {"pink": load("improvements_pink_hotels.png")})
    result = read_group_houses(driver(io), ("pink",))
    assert result.complete, result.problems
    assert result.houses == {"Virginia Avenue": 5, "States Avenue": 5, "St. Charles Place": 5}
    assert io.taps == [
        (ZOOM_ENTRY["pink"].x, ZOOM_ENTRY["pink"].y),
        (HELP_DISMISS.x, HELP_DISMISS.y),
        (ZOOM_RETURN.x, ZOOM_RETURN.y),
    ]
    assert io.captures <= 5  # 1 つの色グループは、取得 5 回以内(判別と読み取りを同じ画像で)


def test_reads_the_zoomed_board_of_the_opponents_group() -> None:
    io = FakeIo(load("my_turn_end_turn.png"), {"light_blue": load("zoomed_light_blue.png")})
    result = read_group_houses(driver(io), ("light_blue",))
    assert result.complete, result.problems
    assert result.houses == {
        "Connecticut Avenue": 0,
        "Vermont Avenue": 0,
        "Oriental Avenue": 0,
    }


def test_opens_only_the_requested_groups() -> None:
    io = FakeIo(
        load("my_turn_end_turn.png"),
        {
            "pink": load("improvements_pink_hotels.png"),
            "orange": load("improvements_orange.png"),
            "red": load("zoomed_red_no_houses.png"),
        },
    )
    result = read_group_houses(driver(io), ("orange", "red"))
    assert result.complete, result.problems
    assert set(result.houses) == {
        "New York Avenue",
        "Tennessee Avenue",
        "St. James Place",
        "Kentucky Avenue",
        "Indiana Avenue",
        "Illinois Avenue",
    }
    opened = [t for t in io.taps if t in {(ZOOM_ENTRY[g].x, ZOOM_ENTRY[g].y) for g in ZOOM_ENTRY}]
    assert opened == [
        (ZOOM_ENTRY["orange"].x, ZOOM_ENTRY["orange"].y),
        (ZOOM_ENTRY["red"].x, ZOOM_ENTRY["red"].y),
    ]


def test_a_group_that_does_not_open_is_a_problem_but_the_board_is_restored() -> None:
    io = FakeIo(load("my_turn_end_turn.png"), {})  # 押しても、盤のまま
    result = read_group_houses(driver(io), ("orange",))
    assert not result.complete and result.houses == {}


def test_refuses_to_start_off_the_board() -> None:
    io = FakeIo(load("improvements_orange.png"), {})
    result = read_group_houses(driver(io), ("orange",))
    assert not result.complete and io.taps == []


def test_abnormal_color_is_refused() -> None:
    image = load("my_turn_end_turn.png").copy()
    image[...] = (image * 0.6).astype(np.uint8)  # 色補正のように、全体の色を変える
    io = FakeIo(image, {})
    result = read_group_houses(driver(io), ("orange",))
    assert not result.complete and io.taps == []
