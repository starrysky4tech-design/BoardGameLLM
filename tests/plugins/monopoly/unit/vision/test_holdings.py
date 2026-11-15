"""起動時の所有・家の読み直し(vision/holdings.py)の、統合部分のテスト。

画面を読む部分(拡大盤・建設画面)は、棒・家の判定のテスト(test_bars.py)で確かめている。ここでは、複数の表示の読みを
統合する規則、読めない土地の扱い、補い方を、実機で読んだ値(2026-11-07)から手で書いた期待値で確かめる。
"""

from bglm.plugins.monopoly.logic.catalogue import CATALOGUE
from bglm.plugins.monopoly.logic.models import Player
from bglm.plugins.monopoly.logic.snapshot import DeedReading
from bglm.plugins.monopoly.vision import bars
from bglm.plugins.monopoly.vision.holdings import HoldingsResult, merge_view
from bglm.plugins.monopoly.vision.ownership import Owner

SELF = Player.SELF


def convert(read: dict[str, bars.PropertyReading]) -> dict[str, DeedReading | None]:
    return bars.to_deed_readings(read)


def test_merge_adds_new_properties() -> None:
    result = HoldingsResult()
    merge_view(
        result, "brown", {"Baltic Avenue": bars.PropertyReading(Owner.AI, 3, False)}, convert
    )
    assert result.readings["Baltic Avenue"] == DeedReading(owner=Player.AI, houses=3)
    assert result.problems == []


def test_merge_keeps_the_first_reading_when_a_second_view_agrees() -> None:
    result = HoldingsResult()
    reading = {"Reading Railroad": bars.PropertyReading(Owner.ME, 0, False)}
    merge_view(result, "brown", reading, convert)
    merge_view(result, "light_blue", reading, convert)
    assert result.readings["Reading Railroad"] == DeedReading(owner=SELF)
    assert result.problems == []


def test_conflicting_views_make_the_property_unreadable() -> None:
    result = HoldingsResult()
    merge_view(result, "a", {"Boardwalk": bars.PropertyReading(Owner.ME, 0, False)}, convert)
    merge_view(result, "b", {"Boardwalk": bars.PropertyReading(Owner.AI, 0, False)}, convert)
    assert result.readings["Boardwalk"] is None  # 食い違いは、推測で選ばない
    assert any("食い違う" in p for p in result.problems)
    assert not result.complete


def test_name_alias_for_b_and_o() -> None:
    result = HoldingsResult()
    merge_view(
        result, "red", {"B. & O. Railroad": bars.PropertyReading(Owner.ME, 0, False)}, convert
    )
    assert "B&O Railroad" in result.readings


def test_unknown_square_is_a_problem() -> None:
    result = HoldingsResult()
    merge_view(result, "x", {"Nowhere Street": bars.PropertyReading(Owner.ME, 0, False)}, convert)
    assert result.problems and "Nowhere Street" not in result.readings


def test_incomplete_until_all_28_are_read() -> None:
    result = HoldingsResult()
    assert not result.complete
    for name in CATALOGUE:
        result.readings[name] = DeedReading(owner=None)
    assert result.complete
    result.readings["Park Place"] = None
    assert not result.complete  # 1 か所でも読めなければ、完全ではない


def test_unreadable_owner_stays_none() -> None:
    result = HoldingsResult()
    merge_view(result, "x", {"Boardwalk": bars.PropertyReading(None, 0, False)}, convert)
    assert result.readings["Boardwalk"] is None
