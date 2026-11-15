"""画面種別の判別のテスト。実画面の分類は、保存画面(Git 管理外)があるときだけ確かめる。

ラベルは、画面を撮ったときの操作の記録(RESULT.md §9〜§11)と、画像を目で見て付けた。
"""

from pathlib import Path

import cv2
import numpy as np
import pytest

from bglm.plugins.wingspan.logic.models import HABITATS
from bglm.plugins.wingspan.vision.layout import card_rect
from bglm.plugins.wingspan.vision.screens import ScreenKind, classify

DATA = Path("datasets/raw/wingspan/feasibility")
M, H, D, U = ScreenKind.MAT, ScreenKind.HABITAT, ScreenKind.DIALOG, ScreenKind.UNKNOWN
C = ScreenKind.CONFIRM

# (画像名, 種別, 案内パネルの有無)
LABELS = [
    # 全体ボード(何も重ならない。自分・相手)
    ("274", M, False),
    ("290", M, False),
    ("297_hand6", M, False),
    ("131_mat", M, False),
    ("029_tab1", M, False),
    ("233_opp", M, False),
    # 全体ボード + 案内パネル(産卵、餌の選択、支払い、札を引く)
    ("275_lay", M, True),
    ("270_eggs", M, True),
    ("285", M, True),
    ("119_mat", M, True),
    ("030_forest_action", M, True),
    ("255_draw", M, True),
    ("291", M, True),
    # 札を選んだ後の引く画面(持ち上がった大きい札が、盤の上端を覆う)
    ("065_take_tray", M, True),
    ("292", M, True),
    ("362_now", M, True),
    ("372_now", M, True),
    ("378_now", M, True),
    (
        "413_now",
        M,
        True,
    ),  # 3 枚選んだ後。持ち上がった札 3 枚で革色が 0.20 まで下がる`n    ("379_now", M, True),  # 2 枚選んだ後。持ち上がった札 2 枚で革色が 0.30 まで下がる
    # 中央のパネル(手番の開始、ラウンドの採点、終局、ストアの案内)
    ("288", D, False),
    ("289", D, False),
    ("166a", D, False),
    ("108_round_end_2", D, False),
    ("277_r1end", D, False),
    ("176_final", D, False),
    ("001_initial", D, False),
    # 確認ダイアログ(スキップ。背景が暗くなる)
    ("034_skip_power", C, False),
    ("099_skip", C, False),
    ("137a", C, False),
    ("284", C, False),
    ("310_after_gainfood", C, False),
    ("312_skip_dialog", C, False),
    # 生息地の表示
    ("016_my_turn", H, False),
    ("023_turn2", H, False),
    ("020_drag_card", H, True),
    ("104_food_convert", H, True),
    ("451_mat", H, False),  # 描画が左へ約 44px ずれた対局(菱形が x≈97)。固定の位置では見つからない
    # 判別しない画面(メニュー、初期選択、保存中の対局の一覧)
    ("002_menu", U, False),
    ("003_play", U, False),
    ("004_custom", U, False),
    ("009_turn_start", U, False),
    ("053_birds", U, False),
]


@pytest.mark.skipif(not (DATA / "274.png").exists(), reason="実画面が無い(Git 管理外)")
@pytest.mark.parametrize(("name", "kind", "prompt"), LABELS)
def test_recorded_screens_are_classified(name: str, kind: ScreenKind, prompt: bool) -> None:
    image = cv2.imread(str(DATA / f"{name}.png"))
    info = classify(image)
    assert (info.kind, info.prompt) == (kind, prompt)


@pytest.mark.skipif(not (DATA / "274.png").exists(), reason="実画面が無い(Git 管理外)")
@pytest.mark.parametrize("per_row", [3, 4, 5])
def test_crowded_board_is_not_mistaken_for_a_dialog(per_row: int) -> None:
    # 遅い局面で札が各行に並んでも、盤はダイアログと取り違えない(合成: 札を全枠に貼る)
    image = cv2.imread(str(DATA / "131_mat.png"))
    source = cv2.imread(str(DATA / "274.png"))
    for habitat, src_habitat in zip(HABITATS, (HABITATS[0], HABITATS[2], HABITATS[0]), strict=True):
        for column in range(per_row):
            x0, y0, x1, y1 = card_rect(habitat, column)
            sx0, sy0, _, _ = card_rect(src_habitat, 0)
            image[y0:y1, x0:x1] = source[sy0 : sy0 + (y1 - y0), sx0 : sx0 + (x1 - x0)]
    assert classify(image).kind is ScreenKind.MAT


def test_wrong_size_image_is_unknown() -> None:
    assert classify(np.zeros((540, 1216, 3), dtype=np.uint8)).kind is ScreenKind.UNKNOWN


def test_blank_images_are_unknown() -> None:
    black = np.zeros((1080, 2432, 3), dtype=np.uint8)
    assert classify(black) == classify(black.copy())
    assert classify(black).kind is ScreenKind.UNKNOWN
    white = np.full((1080, 2432, 3), 255, dtype=np.uint8)
    assert classify(white).kind is ScreenKind.DIALOG  # 中央が全面の紙色(パネルと同じ特徴)
