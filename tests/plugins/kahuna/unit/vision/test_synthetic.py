"""合成画像による認識部品のテスト(録画・テンプレートが無くても動く)。"""

from typing import cast

import numpy as np

from bglm.core.models import Point
from bglm.plugins.kahuna.logic.models import Player, default_board
from bglm.plugins.kahuna.vision.glyphs import extract_glyphs, group_by_gap, white_mask
from bglm.plugins.kahuna.vision.numbers import read_deck
from bglm.plugins.kahuna.vision.sticks import StickBlob, assign_to_lines, find_blobs
from bglm.plugins.kahuna.vision.templates import TemplateSet

BOARD = default_board()


def _canvas() -> np.ndarray:
    return np.full((1080, 2432, 3), (120, 90, 30), np.uint8)


def _stick(image: np.ndarray, center: Point, colour: tuple[int, int, int]) -> None:
    x, y = center.x, center.y
    image[y - 8 : y + 8, x - 22 : x + 22] = colour  # 44x16: 面積704、縦横比2.75


def test_white_and_black_rectangles_are_found_with_owner() -> None:
    image = _canvas()
    _stick(image, Point(1000, 500), (255, 255, 255))
    _stick(image, Point(1200, 600), (0, 0, 0))
    owners = {b.owner for b in find_blobs(image)}
    assert owners == {Player.ME, Player.OPPONENT}


def test_square_and_tiny_blobs_are_not_sticks() -> None:
    image = _canvas()
    image[480:520, 980:1020] = 255  # 正方形
    image[600:604, 1100:1104] = 255  # 小さすぎる
    assert find_blobs(image) == []


def test_blob_is_assigned_to_nearest_line_and_far_ones_are_ignored() -> None:
    target = BOARD.lines[3].position
    near = StickBlob(Player.ME, Point(target.x + 5, target.y - 4), 700)
    far = StickBlob(Player.ME, Point(10, 10), 700)
    owners, unassigned = assign_to_lines(BOARD, [near, far])
    assert owners[3] is Player.ME
    assert sum(o is not None for o in owners) == 1
    assert unassigned == []


def test_two_blobs_on_one_line_leave_one_unassigned() -> None:
    target = BOARD.lines[3].position
    a = StickBlob(Player.ME, Point(target.x + 5, target.y), 700)
    b = StickBlob(Player.OPPONENT, Point(target.x - 30, target.y), 700)
    owners, unassigned = assign_to_lines(BOARD, [a, b])
    assert owners[3] is Player.ME
    assert unassigned == [b]


def test_missing_deck_pile_reads_as_zero_cards() -> None:
    empty_sea = _canvas()
    reading = read_deck(empty_sea, cast(TemplateSet, None))  # 空なら、テンプレートは使わない
    assert (reading.value, reading.confidence) == ("0", 1.0)


def test_glyph_extraction_and_grouping() -> None:
    mask = np.zeros((60, 120), np.uint8)
    mask[10:50, 5:25] = 255  # 1文字目
    mask[10:50, 30:50] = 255  # 隙間5
    mask[10:50, 90:110] = 255  # 隙間40
    glyphs = extract_glyphs(mask)
    assert [g[0] for g in glyphs] == [5, 30, 90]
    assert [len(g) for g in group_by_gap(glyphs, 7)] == [2, 1]


def test_white_mask_circle_excludes_corners() -> None:
    roi = np.full((48, 48, 3), 255, np.uint8)
    masked = white_mask(roi, circle=True)
    assert masked[24, 24] == 255 and masked[0, 0] == 0
