"""餌箱のダイスの読み取りのテスト。実画面の正解は、トレイを画像で目視した面(2026-11-14)。

面の色は実測(feeder.py の docstring)。合成画像でも、数と面の分類を確かめる。
"""

from pathlib import Path

import cv2
import numpy as np
import pytest

from bglm.plugins.wingspan.logic.models import INV_OR_SEED
from bglm.plugins.wingspan.vision.feeder import TRAY, UNKNOWN_FACE, feeder_faces, read_feeder

DATA = Path("datasets/raw/wingspan/feasibility")
needs_real = pytest.mark.skipif(not (DATA / "274.png").exists(), reason="実画面が無い(Git 管理外)")

TRAY_BROWN = (45, 70, 110)  # BGR
CREAM = (190, 220, 235)  # BGR


def synthetic(dice: list[tuple[int, int, tuple[int, int, int]]]) -> np.ndarray:
    """トレイの上に、クリーム色の丸いダイス(実物は角が丸い)を置き、真ん中に色の絵(四角)を描く。"""
    image = np.zeros((1080, 2432, 3), dtype=np.uint8)
    x0, y0, x1, y1 = TRAY
    image[y0:y1, x0:x1] = TRAY_BROWN
    for cx, cy, icon in dice:
        cv2.circle(image, (cx, cy), 21, CREAM, thickness=-1)
        cv2.rectangle(image, (cx - 8, cy - 8), (cx + 8, cy + 8), icon, thickness=-1)
    return image


def test_empty_tray_has_no_dice() -> None:
    assert read_feeder(synthetic([])) == []


def test_synthetic_dice_are_counted_and_classified() -> None:
    # BGR: 赤 = 果実、青緑 = 魚、緑 = 虫(HSV で実測の範囲に入る色)
    red, teal, green = (40, 30, 190), (130, 120, 10), (60, 110, 10)
    image = synthetic([(2060, 260, red), (2100, 320, teal), (2060, 390, green)])
    assert feeder_faces(image) == ("fish", "fruit", "invertebrate")


def test_adjacent_dice_are_counted_separately() -> None:
    # 近接するダイス(間隔 10 px)は別々に数える。触れ合うダイス(実物)は、実画面の 290・030 のテストで確かめる
    red = (40, 30, 190)
    image = synthetic([(2062, 300, red), (2062 + 52, 300, red)])
    assert len(read_feeder(image)) == 2


def test_die_without_a_recognizable_icon_is_unknown_not_guessed() -> None:
    gray = (128, 128, 128)  # どの絵の色にも当てはまらない
    assert feeder_faces(synthetic([(2070, 300, gray)])) == (UNKNOWN_FACE,)


@needs_real
@pytest.mark.parametrize(
    ("name", "faces"),
    [
        ("274", ["fish"]),
        ("297_hand6", ["invertebrate"]),
        ("290", ["invertebrate", "rodent", "rodent"]),
        # 5 個: 果実、種、種、虫/種、虫/種(030_forest_action を目視)
        ("030_forest_action", ["fruit", "seed", "seed", INV_OR_SEED, INV_OR_SEED]),
        # 5 個: 魚、虫、虫、ネズミ、虫/種(233_opp を目視)
        ("233_opp", ["fish", "invertebrate", "invertebrate", "rodent", INV_OR_SEED]),
        ("061_mat", ["fruit", "seed", "seed", INV_OR_SEED]),
        ("147_start", ["fish", "rodent", INV_OR_SEED]),
    ],
)
def test_real_screens_feeder_faces(name: str, faces: list[str]) -> None:
    image = cv2.imread(str(DATA / f"{name}.png"))
    assert sorted(feeder_faces(image)) == sorted(faces)
