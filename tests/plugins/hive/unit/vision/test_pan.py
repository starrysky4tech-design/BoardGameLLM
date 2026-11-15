"""盤が画面の端で切れているかの判定(実機の画面で確かめた事象)。"""

from pathlib import Path

import cv2
import pytest

from bglm.plugins.hive.vision.wide import board_clipped

CLIPPED = Path("datasets/raw/hive/feasibility/debug/step9.png")
CENTRED = Path("datasets/raw/hive/feasibility/26_after_ant3.png")


@pytest.mark.skipif(not CLIPPED.exists(), reason="記録画面が無い(Git管理外)")
def test_clipped_board_is_detected_on_the_right() -> None:
    assert board_clipped(cv2.imread(str(CLIPPED))) == 1


@pytest.mark.skipif(not CENTRED.exists(), reason="記録画面が無い(Git管理外)")
def test_centred_board_is_not_clipped() -> None:
    assert board_clipped(cv2.imread(str(CENTRED))) == 0
