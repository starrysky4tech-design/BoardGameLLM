"""カードトレイと、札の卵の読み取りのテスト。実画面の正解は、画像を目視した値と、右端の「卵 x/y」との一致で確かめた。"""

from pathlib import Path

import cv2
import numpy as np
import pytest

from bglm.plugins.wingspan.logic.cards import default_table
from bglm.plugins.wingspan.logic.models import UNKNOWN_CARD, Habitat
from bglm.plugins.wingspan.vision.layout import card_rect, egg_centers, tray_rect
from bglm.plugins.wingspan.vision.mat import count_eggs, has_card
from bglm.plugins.wingspan.vision.ocr import JAPANESE_REC_MODEL, japanese_reader
from bglm.plugins.wingspan.vision.tray import read_tray

BIRDS = default_table().birds
F, G, W = Habitat.FOREST, Habitat.GRASSLAND, Habitat.WETLAND
DATA = Path("datasets/raw/wingspan/feasibility")
needs_real = pytest.mark.skipif(not (DATA / "274.png").exists(), reason="実画面が無い(Git 管理外)")
needs_ocr = pytest.mark.skipif(
    not JAPANESE_REC_MODEL.exists() or not (DATA / "274.png").exists(),
    reason="日本語の認識モデルまたは実画面が無い(Git 管理外)",
)

PAPER = (190, 220, 235)  # BGR
GOLD = (60, 170, 230)  # BGR: 黄金色の卵(色相 約 20)


def card_with_eggs(filled: int, empty: int) -> np.ndarray:
    image = np.zeros((1080, 2432, 3), dtype=np.uint8)
    x0, y0, x1, y1 = card_rect(F, 0)
    image[y0:y1, x0:x1] = PAPER
    for k, (cx, cy) in enumerate(egg_centers(F, 0)[: filled + empty]):
        color = GOLD if k < filled else (245, 245, 245)  # 空きは白い楕円
        cv2.ellipse(image, (cx, cy), (6, 8), 0, 0, 360, color, thickness=-1)
    return image


@pytest.mark.parametrize(("filled", "empty"), [(0, 4), (2, 2), (4, 0), (6, 0), (0, 0)])
def test_synthetic_eggs_are_counted(filled: int, empty: int) -> None:
    assert count_eggs(card_with_eggs(filled, empty), F, 0) == filled


@needs_real
@pytest.mark.parametrize(
    ("name", "forest", "wetland"),
    [
        # 右端の「卵 x/y」の x と、鳥ごとの合計が一致する画面(画像で確認)
        ("274", 2, 0),  # 2/8
        ("297_hand6", 4, 2),  # 6/8
        ("290", 4, 0),  # 4/8
    ],
)
def test_real_screens_eggs_match_the_side_counter(name: str, forest: int, wetland: int) -> None:
    image = cv2.imread(str(DATA / f"{name}.png"))
    assert has_card(image, F, 0) and has_card(image, W, 0)
    assert count_eggs(image, F, 0) == forest
    assert count_eggs(image, W, 0) == wetland


@needs_real
def test_real_screen_eggs_on_second_row() -> None:
    # 131_mat: 草原のオウゴンヒワに卵 3(上限 3 に達した)。森林の 2 羽は 0
    image = cv2.imread(str(DATA / "131_mat.png"))
    assert count_eggs(image, G, 0) == 3
    assert count_eggs(image, F, 0) == 0 and count_eggs(image, F, 1) == 0


def test_empty_tray_slots_are_none() -> None:
    image = np.zeros((1080, 2432, 3), dtype=np.uint8)
    assert read_tray(image, lambda *_: ["ミサゴ"], BIRDS) == [None, None, None]


def test_tray_reads_names_with_a_fake_ocr_and_marks_unknown_cards() -> None:
    image = np.zeros((1080, 2432, 3), dtype=np.uint8)
    for index in range(3):
        x0, y0, x1, y1 = tray_rect(index)
        image[y0:y1, x0:x1] = PAPER
    texts = iter(["三サゴ", "イナゴヒメドリ", ""])  # 「ミ」を「三」と誤読、表に無い札、読めない
    slots = read_tray(image, lambda *_: [next(texts)], BIRDS)
    assert [s.name if s else None for s in slots] == ["ミサゴ", UNKNOWN_CARD, UNKNOWN_CARD]
    assert slots[1] is not None and slots[1].text == "イナゴヒメドリ"  # 表に無い札は文字列を残す


@needs_ocr
@pytest.mark.parametrize(
    ("name", "names"),
    [
        ("297_hand6", [UNKNOWN_CARD, "ミサゴ", "キバシカッコウ"]),  # イナゴヒメドリは表に無い
        (
            "274",
            [UNKNOWN_CARD, "シマセゲラ", "アカハシリュウキュウガモ"],
        ),  # クロコウウチョウは表に無い
        ("290", ["ハシグロアビ", "ミサゴ", "キバシカッコウ"]),
        ("131_mat", ["ハシビロガモ", UNKNOWN_CARD, UNKNOWN_CARD]),  # 残りは表に無い
        ("253_t5", ["シロハラミソサザイ", "シマセゲラ", "アカハシリュウキュウガモ"]),
    ],
)
def test_real_screens_tray(name: str, names: list[str]) -> None:
    image = cv2.imread(str(DATA / f"{name}.png"))
    got = [s.name if s else None for s in read_tray(image, japanese_reader(), BIRDS)]
    assert got == names
