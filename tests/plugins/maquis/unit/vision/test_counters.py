"""数と状態の読み取り(counters.py)の合成画像テスト。記録画面が無くても動く。

座標と色は、実機の画面で測った値(layout.py)。ここでは、その値で描いた画像を正しく読めることと、
読み違えやすい形(塗りが飛ぶ、★が上から点灯)を問題として返すことを確かめる。
"""

import numpy as np
from numpy.typing import NDArray

from bglm.plugins.maquis.vision import layout
from bglm.plugins.maquis.vision.counters import PhaseIcon, read_phase, read_resources, read_stars

W, H = layout.SCREEN_SIZE


def blank() -> NDArray[np.uint8]:
    return np.full((H, W, 3), 70, dtype=np.uint8)  # 空の丸(暗い)と同じ明るさ


def fill(image: NDArray[np.uint8], x: int, y: int, value: int = 200) -> None:
    image[y - 8 : y + 9, x - 8 : x + 9] = value


def paint(image: NDArray[np.uint8], counts: dict[str, int]) -> None:
    for name, rows in layout.RESOURCE_ROWS.items():
        remaining = counts.get(name, 0)
        widths = layout.MORALE_ROW_COUNTS if name == "morale" else (4,)
        for y, columns in zip(rows, widths, strict=False):
            for x in layout.RESOURCE_COLS[:columns]:
                if remaining > 0:
                    fill(image, x, y)
                    remaining -= 1


def test_resources_are_counted_from_the_filled_circles() -> None:
    image = blank()
    paint(image, {"morale": 6, "food": 2, "medicine": 1, "explosives": 4})
    reading = read_resources(image)
    assert reading.problems == ()
    res = reading.resources
    assert res is not None
    assert (res.morale, res.food, res.medicine, res.funds, res.intel, res.guns, res.explosives) == (
        6,
        2,
        1,
        0,
        0,
        0,
        4,
    )


def test_morale_counts_across_both_rows() -> None:
    image = blank()
    paint(image, {"morale": 7})
    res = read_resources(image).resources
    assert res is not None
    assert res.morale == 7


def test_a_gap_in_the_filled_circles_is_a_problem_not_a_guess() -> None:
    # 食料の1つ目と3つ目だけが塗り(2つ目が空)。左から連続していないので、数えずに問題とする
    image = blank()
    row = layout.RESOURCE_ROWS["food"][0]
    fill(image, layout.RESOURCE_COLS[0], row)
    fill(image, layout.RESOURCE_COLS[2], row)
    reading = read_resources(image)
    assert reading.resources is None
    assert reading.problems == ("resource_gap:food",)


def star_image(lit: list[bool], slot: str) -> NDArray[np.uint8]:
    image = blank()
    for (x, y), on in zip(layout.MISSION_STARS[slot], lit, strict=True):
        color = layout.STAR_LIT_BGR if on else layout.STAR_OFF_BGR
        image[y - 8 : y + 9, x - 8 : x + 9] = color
    return image


def test_stars_light_from_the_bottom() -> None:
    # 実機: 任務B(★3つ)の1つ目は一番下が点灯した
    assert read_stars(star_image([False, False, True], "mission_b"), "mission_b") == (1, True)
    assert read_stars(star_image([False, True, True], "mission_b"), "mission_b") == (2, True)
    assert read_stars(star_image([False, False, False], "mission_b"), "mission_b") == (0, True)


def test_stars_lit_from_the_top_are_flagged() -> None:
    assert read_stars(star_image([True, False, False], "mission_b"), "mission_b") == (1, False)


def phase_image(r: int, g: int, b: int) -> NDArray[np.uint8]:
    image = blank()
    x0, y0, x1, y1 = layout.PHASE_BOX
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    # アイコンの縁(円)の色。中心は黒い絵
    image[cy - 38 : cy + 38, cx - 38 : cx + 38] = (b, g, r)
    image[cy - 15 : cy + 15, cx - 15 : cx + 15] = 0
    return image


def test_phase_icon_is_read_from_the_ring_colour() -> None:
    assert read_phase(phase_image(240, 160, 80))[0] is PhaseIcon.FLAG  # 橙: 行動フェイズ
    assert read_phase(phase_image(195, 195, 110))[0] is PhaseIcon.BICYCLE  # 黄緑: 配置フェイズ


def test_phase_icon_is_unknown_on_a_dimmed_screen() -> None:
    # 終局のダイアログなどで暗くなった画面。推測しない
    assert read_phase(blank())[0] is None
