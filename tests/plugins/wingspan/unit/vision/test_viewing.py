"""表示中の盤の持ち主の判別のテスト。実画面は、保存画面(Git 管理外)があるときだけ確かめる。

注意: 目のテンプレートは 233_opp から切った(学習データ内)。別の対局の画面で再検証が要る。
"""

from pathlib import Path

import cv2
import numpy as np
import pytest

from bglm.plugins.wingspan.vision.viewing import (
    HOURGLASS,
    TEMPLATE,
    Viewing,
    find_eye,
    opponent_is_playing,
    viewing,
)

DATA = Path("datasets/raw/wingspan/feasibility")
needs_real = pytest.mark.skipif(not (DATA / "274.png").exists(), reason="実画面が無い(Git 管理外)")


def test_templates_exist() -> None:
    assert TEMPLATE.exists() and HOURGLASS.exists()


def test_blank_screen_without_an_eye_is_my_board() -> None:
    # 目の印が無ければ自分の盤(自分の盤には目の印が出ない)
    assert viewing(np.zeros((1080, 2432, 3), dtype=np.uint8)) is Viewing.ME


@needs_real
@pytest.mark.parametrize(
    ("name", "expected"),
    [
        # 自分の盤(目の印なし)。先手によって肖像の左右が入れ替わる画面を含む
        ("274", Viewing.ME),
        ("290", Viewing.ME),
        ("280_me", Viewing.ME),
        ("297_hand6", Viewing.ME),
        ("131_mat", Viewing.ME),
        # 相手の盤(橙の肖像の下に目の印)。肖像が右にある画面(279)を含む
        ("233_opp", Viewing.OPPONENT),
        ("279_opp", Viewing.OPPONENT),
        ("245_opp", Viewing.OPPONENT),
        ("253_t5", Viewing.OPPONENT),
        ("025_opp_board", Viewing.OPPONENT),  # 1 局目
    ],
)
def test_real_screens_viewing(name: str, expected: Viewing) -> None:
    assert viewing(cv2.imread(str(DATA / f"{name}.png"))) is expected


@needs_real
def test_eye_is_found_below_the_viewed_portrait() -> None:
    left = find_eye(cv2.imread(str(DATA / "233_opp.png")))
    right = find_eye(cv2.imread(str(DATA / "279_opp.png")))
    assert left is not None and right is not None
    assert left[0] < 1200 < right[0]  # 肖像の左右が入れ替わると、目の印の位置も替わる


def test_blank_screen_is_not_the_opponents_turn() -> None:
    assert opponent_is_playing(np.zeros((1080, 2432, 3), dtype=np.uint8)) is False


@needs_real
def test_hourglass_marks_the_opponents_turn() -> None:
    # 302_opp_turn_1: 確定の約 1.2 秒後。橙の肖像が大きく、その下に砂時計(2 局目の実機)
    assert opponent_is_playing(cv2.imread(str(DATA / "302_opp_turn_1.png"))) is True


@needs_real
@pytest.mark.parametrize("name", ["274", "290", "280_me", "297_hand6", "131_mat", "233_opp"])
def test_no_hourglass_on_my_turn_screens(name: str) -> None:
    # 自分の手番の画面(自分の盤・相手の盤の表示のどちらも)には砂時計が出ない
    assert opponent_is_playing(cv2.imread(str(DATA / f"{name}.png"))) is False
