"""画面の読み取り結果から対局の状態を作る(logic/snapshot.py)のテスト。期待値は手で書く。"""

from bglm.plugins.monopoly.logic.catalogue import DEEDS
from bglm.plugins.monopoly.logic.models import HOTEL_LEVEL, Player
from bglm.plugins.monopoly.logic.snapshot import DeedReading, build_snapshot

CATALOGUE = {deed.name: deed for deed in DEEDS}
CASH = {Player.SELF: 161, Player.AI: 78}


def full_readings(**overrides: DeedReading | None) -> dict[str, DeedReading | None]:
    readings: dict[str, DeedReading | None] = {name: DeedReading(owner=None) for name in CATALOGUE}
    readings.update(overrides)
    return readings


def test_owned_and_unowned_become_holdings() -> None:
    readings = full_readings(
        **{
            "Baltic Avenue": DeedReading(owner=Player.AI, houses=3),
            "Oriental Avenue": DeedReading(owner=Player.SELF, houses=1),
        }
    )
    result = build_snapshot(CASH, readings, CATALOGUE)
    assert result.state is not None
    assert result.state.holdings["Baltic Avenue"].owner is Player.AI
    assert result.state.holdings["Baltic Avenue"].houses == 3
    assert result.state.holdings["Oriental Avenue"].owner is Player.SELF
    assert "Vermont Avenue" not in result.state.holdings
    assert dict(result.state.cash) == CASH


def test_hotel_is_five_houses() -> None:
    readings = full_readings(**{"Baltic Avenue": DeedReading(owner=Player.AI, hotel=True)})
    result = build_snapshot(CASH, readings, CATALOGUE)
    assert result.state is not None
    assert result.state.holdings["Baltic Avenue"].houses == HOTEL_LEVEL


def test_unreadable_deed_stops_without_a_state() -> None:
    readings = full_readings(**{"Vermont Avenue": None})
    result = build_snapshot(CASH, readings, CATALOGUE)
    assert result.state is None
    assert "Vermont Avenue" in result.reason


def test_missing_deed_stops() -> None:
    readings = full_readings()
    del readings["Park Place"]
    result = build_snapshot(CASH, readings, CATALOGUE)
    assert result.state is None


def test_houses_on_unowned_deed_are_refused() -> None:
    readings = full_readings(**{"Baltic Avenue": DeedReading(owner=None, houses=2)})
    result = build_snapshot(CASH, readings, CATALOGUE)
    assert result.state is None


def test_houses_on_railroad_are_refused() -> None:
    readings = full_readings(**{"Reading Railroad": DeedReading(owner=Player.SELF, houses=1)})
    result = build_snapshot(CASH, readings, CATALOGUE)
    assert result.state is None
