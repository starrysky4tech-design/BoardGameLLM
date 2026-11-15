"""土地の詳細画面の所有者の判定(vision/ownership.py)のテスト。色だけを置いた合成画像で確かめる。"""

from bglm.core.models import Frame
from bglm.plugins.monopoly.vision import ownership as ow

RED = (25, 20, 173)  # MANAGE PROPERTY の見出し(BGR)
BLUE = (255, 129, 82)  # 自分の所有の箱(BGR)
YELLOW = (74, 239, 255)  # AI の所有の箱(BGR)
CREAM = (235, 248, 255)  # 空の箱(BGR)
PLAIN = (200, 200, 200)  # 見出しが赤くない画面(MANAGE PROPERTY ではない)


def detail(title: tuple[int, int, int], box: tuple[int, int, int]) -> Frame:
    return ow.synthetic_frame(title, box)


def test_every_property_has_a_group_and_a_tile() -> None:
    assert set(ow.PROPERTY_GROUP) == set(ow.ZOOM_TILE)
    for group in ow.PROPERTY_GROUP.values():
        assert group in ow.ZOOM_ENTRY


def test_owner_colors() -> None:
    assert ow.owner_from_image(detail(RED, BLUE).image) == ow.Owner.ME
    assert ow.owner_from_image(detail(RED, YELLOW).image) == ow.Owner.AI
    assert ow.owner_from_image(detail(RED, CREAM).image) == ow.Owner.NONE


def test_non_detail_screen_is_not_read() -> None:
    assert ow.owner_from_image(detail(PLAIN, BLUE).image) is None
