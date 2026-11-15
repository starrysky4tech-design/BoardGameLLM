"""右端の数の読み取りのテスト。実画面の正解は、画像を目で見て確かめた値(RESULT.md §11 の撮影記録とも一致)。

注意: テンプレートは同じ保存画面群から作ったので、これは学習データ内の確認。別の画面での評価は、画面が増えたら足す。
"""

from pathlib import Path

import cv2
import numpy as np
import pytest

from bglm.plugins.wingspan.logic.models import FOODS, Food
from bglm.plugins.wingspan.vision import layout
from bglm.plugins.wingspan.vision.counters import hud_shift, read_counters
from bglm.plugins.wingspan.vision.digits import (
    classify_glyph,
    load_templates,
    read_number,
    segment_glyphs,
)

DATA = Path("datasets/raw/wingspan/feasibility")
needs_real = pytest.mark.skipif(not (DATA / "274.png").exists(), reason="実画面が無い(Git 管理外)")


def food_tuple(**counts: int) -> tuple[int, ...]:
    return tuple(counts.get(f.value, 0) for f in FOODS)


def test_templates_exist_for_the_seen_digits() -> None:
    # 保存画面に現れた桁(0〜9)。読めない桁は None で止まる(推測しない)
    assert set(load_templates()) >= set("0123456789")


def test_unreadable_region_returns_none_without_guessing() -> None:
    blank = np.full((1080, 2432, 3), 230, dtype=np.uint8)  # 桁が無い(紙の色だけ)
    assert read_number(blank, layout.counter_rect(layout.CUBE_ROW_Y)) is None
    assert read_number(blank, layout.counter_rect(layout.CUBE_ROW_Y), templates={}) is None


@needs_real
def test_digit_templates_are_distinct_from_each_other() -> None:
    # 桁どうしの照合で、自分自身が 1 位になる(テンプレートの取り違えが無い)
    templates = load_templates()
    for name, glyph in templates.items():
        got = classify_glyph(glyph, templates)
        assert got is not None and got.value == name


@needs_real
@pytest.mark.parametrize(
    ("name", "cubes", "food"),
    [
        # 297_hand6: キューブ 4、果実 0・魚 1・虫 0・ネズミ 0・種 4(画像で確認)
        ("297_hand6", 4, food_tuple(fish=1, seed=4)),
        ("274", 1, food_tuple(seed=2)),
        ("290", 6, food_tuple(fish=1, seed=3)),
    ],
)
def test_real_screens_counters(name: str, cubes: int, food: tuple[int, ...]) -> None:
    got = read_counters(cv2.imread(str(DATA / f"{name}.png")))
    assert got.cubes == cubes
    assert got.food == food


@needs_real
def test_food_order_is_converted_to_the_logic_order() -> None:
    # 画面の並び(果実、魚、虫、ネズミ、種)ではなく、FOODS の並び(虫、種、魚、果実、ネズミ)で返る
    got = read_counters(cv2.imread(str(DATA / "297_hand6.png")))
    assert got.food is not None
    assert got.food[FOODS.index(Food.FISH)] == 1 and got.food[FOODS.index(Food.SEED)] == 4


@needs_real
def test_dimmed_screen_is_unread_not_guessed() -> None:
    # 確認ダイアログで画面が暗くなると、桁の色が変わる。読めないときは None(誤読しない)
    got = read_counters(cv2.imread(str(DATA / "034_skip_power.png")))
    assert got.food is None or all(isinstance(v, int) for v in got.food)


@needs_real
def test_segmentation_finds_one_glyph_per_digit() -> None:
    image = cv2.imread(str(DATA / "297_hand6.png"))
    assert len(segment_glyphs(image, layout.counter_rect(layout.CUBE_ROW_Y))) == 1


@needs_real
def test_counters_follow_a_shifted_hud() -> None:
    # 452_now: 描画が左へ 43px ずれた対局。パネルの左端でずれを測って読む。キューブ 5、虫 2・種 1・魚 2・果実 2・ネズミ 1(目視)
    image = cv2.imread(str(DATA / "452_now.png"))
    assert hud_shift(image) == -43
    got = read_counters(image)
    assert got.cubes == 5 and got.food == food_tuple(
        invertebrate=2, seed=1, fish=2, fruit=2, rodent=1
    )
    assert hud_shift(cv2.imread(str(DATA / "290.png"))) == 0


@needs_real
def test_cube_count_eight_at_the_start_of_a_game() -> None:
    # 新しい対局のキューブは 8 個(ラウンド 1)。361_mat8: キューブ 8、餌は各 1(目視)
    got = read_counters(cv2.imread(str(DATA / "361_mat8.png")))
    assert got.cubes == 8 and got.food == (1, 1, 1, 1, 1)


@needs_real
def test_food_count_nine_is_read() -> None:
    # 408_nine: 魚が 9、キューブが 5(目視。対局 4 局目のラウンド 3)
    got = read_counters(cv2.imread(str(DATA / "408_nine.png")))
    assert got.cubes == 5 and got.food == food_tuple(fish=9)
