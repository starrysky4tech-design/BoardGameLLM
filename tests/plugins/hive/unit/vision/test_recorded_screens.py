"""記録した実画面での読み取りの確認。画面の素材は Git 管理外(datasets/)なので、無ければ飛ばす。

期待値は画面の色を目で見て決めた(白の地・黒の地と、絵の色: 橙=女王、青=アリ、緑=バッタ、紫=カブトムシ、茶=クモ)。
"""

from pathlib import Path

import cv2
import pytest
from tests.plugins.hive.support.helpers import B, W, at

from bglm.plugins.hive.logic.models import Color, Kind
from bglm.plugins.hive.vision.recognizer import _shifted, read_board

SCREEN = Path("datasets/raw/hive/feasibility/26_after_ant3.png")


@pytest.mark.skipif(not SCREEN.exists(), reason="記録画面が無い(Git管理外)")
def test_board_after_three_moves_is_read_without_problems() -> None:
    reading = read_board(cv2.imread(str(SCREEN)))
    assert reading.problems == ()
    assert reading.confidence >= 0.5
    expected = {
        at(3, 0): (W, Kind.QUEEN),
        at(3, 1): (B, Kind.ANT),
        at(4, 1): (B, Kind.ANT),
        at(2, 2): (B, Kind.ANT),
        at(1, 3): (B, Kind.GRASSHOPPER),
        at(2, 3): (B, Kind.QUEEN),
        at(3, 3): (W, Kind.ANT),
        at(1, 4): (W, Kind.ANT),
        at(0, 5): (W, Kind.GRASSHOPPER),
    }
    got = {k: (p.color, p.kind) for k, p in _shifted(reading.tops).items()}
    assert got == expected
    assert sum(1 for c, _ in got.values() if c is Color.BLACK) == 5
