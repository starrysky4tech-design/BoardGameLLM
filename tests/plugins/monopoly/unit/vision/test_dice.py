"""ダイスの目の読み取り(vision/dice.py)のテスト。

合成画像: 黒い立方体の上の面に、純白の点を置く。分岐(2 個、接した 2 個、不明)を確かめる。
実機の画面: datasets/eval/monopoly/dice3/(Git 管理外)。無い環境では飛ばす。
"""

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from bglm.plugins.monopoly.vision import dice

DATA = Path("datasets/eval/monopoly/dice3")

# 上の面の点の配置(面の中心からの相対位置、px)。面は約 22 px 四方
LAYOUT: dict[int, list[tuple[int, int]]] = {
    1: [(0, 0)],
    2: [(-6, -6), (6, 6)],
    3: [(-6, -6), (0, 0), (6, 6)],
    4: [(-6, -6), (6, -6), (-6, 6), (6, 6)],
    5: [(-6, -6), (6, -6), (0, 0), (-6, 6), (6, 6)],
    6: [(-6, -6), (6, -6), (-6, 0), (6, 0), (-6, 6), (6, 6)],
}


def draw_die(image: np.ndarray, center: tuple[int, int], value: int) -> None:
    cx, cy = center
    cv2.rectangle(
        image, (cx - 13, cy - 13), (cx + 13, cy + 25), (0, 0, 0), -1
    )  # 本体(上の面 + 手前の面)
    for dx, dy in LAYOUT[value]:
        cv2.rectangle(
            image, (cx + dx - 2, cy + dy - 1), (cx + dx + 2, cy + dy + 1), (255, 255, 255), -1
        )


def board(*dice_at: tuple[tuple[int, int], int]) -> np.ndarray:
    image = np.full((1080, 2432, 3), (205, 230, 210), dtype=np.uint8)  # 盤の薄い緑
    for center, value in dice_at:
        draw_die(image, center, value)
    return image


def test_two_separate_dice_are_read_left_to_right() -> None:
    reading = dice.read_dice(board(((1000, 450), 3), ((1300, 600), 5)))
    assert reading.values == (3, 5)
    assert reading.total == 8


def test_doubles_are_read() -> None:
    assert dice.read_dice(board(((1000, 450), 4), ((1300, 600), 4))).values == (4, 4)


def test_two_face_with_wide_diagonal_is_one_die() -> None:
    assert dice.read_dice(board(((1000, 450), 2), ((1300, 600), 6))).values == (2, 6)


def test_touching_dice_are_split() -> None:
    reading = dice.read_dice(board(((1200, 500), 5), ((1236, 506), 5)))
    assert reading.values == (5, 5)


def test_one_die_is_unknown() -> None:
    assert dice.read_dice(board(((1000, 450), 3))) == dice.UNKNOWN


def test_no_dice_is_unknown() -> None:
    assert dice.read_dice(board()) == dice.UNKNOWN


def test_front_face_pips_are_not_counted() -> None:
    # 手前の面の点は平たく、純白の画素が少ない(1 行 × 高さ 1)。数えない
    image = board(((1000, 450), 3), ((1300, 600), 5))
    for x in (990, 1000, 1010):
        image[(450 + 20), x - 2 : x + 2] = (255, 255, 255)
    assert dice.read_dice(image).values == (3, 5)


def test_off_white_blob_is_not_a_pip() -> None:
    # マスコットの目やひげのような、青の成分が 230 までの白っぽい塊は点ではない
    image = board(((1000, 450), 3), ((1300, 600), 5))
    cv2.rectangle(image, (1500, 500), (1504, 503), (230, 243, 247), -1)
    cv2.rectangle(image, (1490, 490), (1514, 520), (20, 20, 20), 2)
    assert dice.read_dice(image).values == (3, 5)


def test_dialog_over_the_board_is_unknown() -> None:
    # Chance カードのような白いダイアログが盤を覆う。文字の穴(O や D の内側)を点と取り違えない
    image = board()
    cv2.rectangle(image, (800, 305), (1715, 780), (255, 255, 255), -1)
    for cx in (960, 1010, 1060, 1110):
        cv2.rectangle(image, (cx - 18, 560), (cx + 18, 590), (0, 0, 0), -1)  # 黒い文字
        cv2.rectangle(image, (cx - 3, 571), (cx + 3, 578), (255, 255, 255), -1)  # 文字の穴
    assert dice.read_dice(image) == dice.UNKNOWN


def _samples() -> list[tuple[str, tuple[int, ...]]]:
    path = DATA / "labels.json"
    if not path.exists():
        return []
    labels = json.loads(path.read_text(encoding="utf-8"))
    return [(name, tuple(item["dice"] or ())) for name, item in labels.items()]


@pytest.mark.parametrize(("name", "expected"), _samples() or [("none", ())])
def test_real_screens_match_labels(name: str, expected: tuple[int, ...]) -> None:
    if not _samples():
        pytest.skip(f"実機の見本が無い: {DATA}")
    image = cv2.imread(str(DATA / name))
    assert image is not None
    values = dice.read_dice(np.asarray(image, dtype=np.uint8)).values
    if not expected:  # ダイスが写っていない画面(ダイアログなど)は、不明を返す
        assert values is None
        return
    assert values is not None
    assert tuple(sorted(values)) == tuple(sorted(expected))
