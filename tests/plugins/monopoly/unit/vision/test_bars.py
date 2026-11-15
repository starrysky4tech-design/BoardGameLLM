"""棒による所有者の読み取り(vision/bars.py)のテスト。合成画像で、棒の割り当てと色の判定を確かめる。"""

import numpy as np

from bglm.plugins.monopoly.logic.models import Player
from bglm.plugins.monopoly.logic.snapshot import DeedReading
from bglm.plugins.monopoly.vision import bars as bb
from bglm.plugins.monopoly.vision.ownership import Owner

BLUE_BGR = (255, 0, 0)
YELLOW_BGR = (0, 255, 255)


def paint(view: bb.View, owners: dict[str, Owner]) -> np.ndarray:
    """view の下段に、owners の色の棒を土地の中心へ描いた画像(原寸)。"""
    image = np.full((1080, 2432, 3), 200, dtype=np.uint8)
    y0, y1 = view.band
    for name, x in view.tiles:
        owner = owners.get(name)
        if owner is None or owner == Owner.NONE:
            continue
        color = BLUE_BGR if owner == Owner.ME else YELLOW_BGR
        cx = round(x * bb.DISPLAY_TO_FRAME)
        half = (view.bar_w[0] + view.bar_w[1]) // 4
        image[y0 + 5 : y1 - 5, cx - half : cx + half] = color
    return image


def test_views_cover_all_twenty_eight_properties() -> None:
    names = {name for view in bb.VIEWS.values() for name, _ in view.tiles}
    assert len(names) == 28


def test_mixed_row_reads_each_tile() -> None:
    view = bb.VIEWS["pink"]
    owners = {
        "St. James Place": Owner.NONE,
        "Pennsylvania Railroad": Owner.AI,
        "Virginia Avenue": Owner.ME,
        "States Avenue": Owner.AI,
        "Electric Company": Owner.ME,
        "St. Charles Place": Owner.ME,
    }
    result = bb.read_view(paint(view, owners), view)
    assert result == owners


def test_each_bar_color_maps_to_owner() -> None:
    view = bb.VIEWS["brown"]
    owners = {
        "Oriental Avenue": Owner.ME,
        "Reading Railroad": Owner.ME,
        "Baltic Avenue": Owner.AI,
        "Mediterranean Avenue": Owner.AI,
    }
    assert bb.read_view(paint(view, owners), view) == owners


def test_no_bars_means_unowned() -> None:
    view = bb.VIEWS["red"]
    image = paint(view, {})
    assert set(bb.read_view(image, view).values()) == {Owner.NONE}


def test_two_bars_on_one_tile_is_unreadable() -> None:
    view = bb.VIEWS["green"]
    image = np.full((1080, 2432, 3), 200, dtype=np.uint8)
    cx = round(630 * bb.DISPLAY_TO_FRAME)
    y0, y1 = view.band
    # 同じ土地の下に、間を空けて 2 本の棒を置く(どちらも Short Line に割り当たる)
    image[y0 + 5 : y1 - 5, cx - 115 : cx - 5] = YELLOW_BGR
    image[y0 + 5 : y1 - 5, cx + 5 : cx + 115] = BLUE_BGR
    assert bb.read_view(image, view)["Short Line"] is None


def test_global_bottom_row_is_read_in_its_own_band() -> None:
    view = bb.VIEWS["global_bottom"]
    owners = {
        "Connecticut Avenue": Owner.ME,
        "Vermont Avenue": Owner.ME,
        "Oriental Avenue": Owner.ME,
        "Reading Railroad": Owner.ME,
        "Baltic Avenue": Owner.AI,
        "Mediterranean Avenue": Owner.AI,
    }
    assert bb.read_view(paint(view, owners), view) == owners


def paint_houses(view: bb.View, houses: dict[str, int], hotel: set[str]) -> np.ndarray:
    """土地の上端に、家(緑)とホテル(赤)の四角を描いた画像(原寸)。"""
    image = np.full((1080, 2432, 3), 200, dtype=np.uint8)
    y0, y1 = bb.HOUSE_BAND
    green = (0, 200, 0)
    red = (0, 0, 220)
    for name, x in view.tiles:
        cx = round(x * bb.DISPLAY_TO_FRAME)
        for k in range(houses.get(name, 0)):
            left = cx - 60 + k * 50
            image[y0 + 10 : y0 + 50, left : left + 44] = green
        if name in hotel:
            left = cx - 60
            image[y0 + 10 : y0 + 50, left : left + 44] = red
    return image


def test_house_count_reads_per_tile() -> None:
    view = bb.VIEWS["brown"]
    image = paint_houses(view, {"Baltic Avenue": 3, "Mediterranean Avenue": 2}, set())
    counts = bb.read_buildings(image, view)
    assert counts["Baltic Avenue"] == bb.Buildings(houses=3, hotel=False)
    assert counts["Mediterranean Avenue"] == bb.Buildings(houses=2, hotel=False)
    assert counts["Oriental Avenue"] == bb.Buildings(houses=0, hotel=False)


def test_hotel_is_read_as_hotel() -> None:
    view = bb.VIEWS["brown"]
    image = paint_houses(view, {}, {"Baltic Avenue"})
    assert bb.read_buildings(image, view)["Baltic Avenue"] == bb.Buildings(houses=0, hotel=True)


def test_full_reading_combines_owner_and_buildings() -> None:
    view = bb.VIEWS["brown"]
    owners = {"Baltic Avenue": Owner.AI, "Mediterranean Avenue": Owner.AI}
    image = paint(view, owners)
    houses = paint_houses(view, {"Baltic Avenue": 3}, set())
    image = np.minimum(image, houses)  # 2 枚を重ねる(どちらも白地に色)
    reading = bb.read_view_full(image, view)
    assert reading["Baltic Avenue"].owner == Owner.AI
    assert reading["Baltic Avenue"].houses == 3


def test_conversion_to_logic_input() -> None:
    readings = {
        "Baltic Avenue": bb.PropertyReading(owner=Owner.AI, houses=3, hotel=False),
        "Vermont Avenue": bb.PropertyReading(owner=Owner.NONE, houses=0, hotel=False),
        "Oriental Avenue": bb.PropertyReading(owner=None, houses=0, hotel=False),
    }
    converted = bb.to_deed_readings(readings)
    assert converted["Baltic Avenue"] == DeedReading(owner=Player.AI, houses=3)
    assert converted["Vermont Avenue"] == DeedReading(owner=None)
    assert converted["Oriental Avenue"] is None
