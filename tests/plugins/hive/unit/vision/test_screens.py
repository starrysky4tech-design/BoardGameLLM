"""画面の種類の判定の単体テスト。判定の表(読み取りの結果 → 画面の種類)を確かめる。"""

from pathlib import Path

import cv2
import pytest

from bglm.plugins.hive.vision.recognizer import read_board
from bglm.plugins.hive.vision.screens import ScreenKind, screen_of

RECORDED = Path("datasets/raw/hive/feasibility")


def test_truth_table() -> None:
    assert screen_of(True, ()) is ScreenKind.BOARD
    assert screen_of(False, ()) is ScreenKind.NO_BOARD
    assert screen_of(True, ("hidden_piece",)) is ScreenKind.OVERLAY
    assert screen_of(False, ("kind@0,0",)) is ScreenKind.OVERLAY
    assert screen_of(False, ("grid_mismatch",)) is ScreenKind.GRID_MISMATCH
    assert screen_of(True, ("grid_mismatch",)) is ScreenKind.GRID_MISMATCH


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("00_launch.png", ScreenKind.NO_BOARD),
        ("02_board_start.png", ScreenKind.BOARD),
        ("26_after_ant3.png", ScreenKind.BOARD),
        ("06_menu.png", ScreenKind.OVERLAY),
        ("12_expansions.png", ScreenKind.GRID_MISMATCH),
    ],
)
def test_recorded_screens(name: str, expected: ScreenKind) -> None:
    path = RECORDED / name
    if not path.exists():
        pytest.skip("記録画面が無い(Git管理外)")
    reading = read_board(cv2.imread(str(path)))
    assert screen_of(bool(reading.tops), reading.problems) is expected
