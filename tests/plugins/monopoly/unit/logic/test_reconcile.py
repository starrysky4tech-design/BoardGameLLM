"""台帳と全体盤の読み取りの照合(logic/reconcile.py)のテスト。"""

from bglm.plugins.monopoly.logic.models import Holding, MonopolyState, Player
from bglm.plugins.monopoly.logic.reconcile import (
    HOUSE_UNITS_TOLERANCE,
    DeedObservation,
    GroupObservation,
    reconcile,
    with_houses,
)

ME, AI = Player.SELF, Player.AI
RED = ("Kentucky Avenue", "Indiana Avenue", "Illinois Avenue")


def state(holdings: dict[str, Holding]) -> MonopolyState:
    return MonopolyState(cash={ME: 500, AI: 500}, holdings=holdings)


def red_monopoly(houses: int = 0) -> dict[str, Holding]:
    return {name: Holding(owner=ME, houses=houses) for name in RED}


def obs(owner: Player | None, mortgaged: bool | None = False) -> DeedObservation:
    return DeedObservation(owner, mortgaged)


# --- 所有 ---


def test_agreement_changes_nothing() -> None:
    s = state({"Boardwalk": Holding(owner=ME)})
    result = reconcile(s, {"Boardwalk": obs(ME), "Park Place": obs(None)}, None)
    assert result.state == s
    assert not result.pending and not result.fixes and not result.unresolved


def test_owner_change_needs_two_matching_reads() -> None:
    s = state({})
    first = reconcile(s, {"Water Works": obs(AI)}, None)
    assert "Water Works" not in first.state.holdings  # 1 回目は保留
    assert first.pending == {("Water Works", "owner", "ai")}
    second = reconcile(s, {"Water Works": obs(AI)}, None, pending=first.pending)
    assert second.state.holdings["Water Works"] == Holding(owner=AI)
    assert second.fixes and not second.pending


def test_owner_change_is_dropped_if_the_next_read_differs() -> None:
    s = state({})
    first = reconcile(s, {"Water Works": obs(AI)}, None)
    second = reconcile(s, {"Water Works": obs(None)}, None, pending=first.pending)
    assert "Water Works" not in second.state.holdings and not second.pending


def test_trusted_applies_at_once_and_keeps_the_mortgage_flag() -> None:
    result = reconcile(state({}), {"Water Works": obs(AI, True)}, None, trusted=True)
    assert result.state.holdings["Water Works"] == Holding(owner=AI, mortgaged=True)


def test_unreadable_tile_is_left_as_in_the_ledger() -> None:
    s = state({"Boardwalk": Holding(owner=ME)})
    result = reconcile(s, {"Boardwalk": None}, None)
    assert result.state == s and not result.unresolved


def test_ledger_owned_but_board_unowned_is_unresolved() -> None:
    s = state({"Boardwalk": Holding(owner=ME)})
    result = reconcile(s, {"Boardwalk": obs(None)}, None)
    assert result.unresolved and result.state == s


def test_owner_change_on_a_tile_with_houses_is_unresolved_and_opens_the_group() -> None:
    s = state(red_monopoly(houses=2))
    result = reconcile(s, {"Indiana Avenue": obs(AI)}, None)
    assert result.unresolved and result.open_groups == ("red",)
    assert result.state == s


# --- 抵当 ---


def test_mortgage_change_needs_two_matching_reads() -> None:
    s = state({"Boardwalk": Holding(owner=ME)})
    first = reconcile(s, {"Boardwalk": obs(ME, True)}, None)
    assert not first.state.holdings["Boardwalk"].mortgaged
    second = reconcile(s, {"Boardwalk": obs(ME, True)}, None, pending=first.pending)
    assert second.state.holdings["Boardwalk"].mortgaged


def test_unreadable_mortgage_flag_is_ignored() -> None:
    s = state({"Boardwalk": Holding(owner=ME, mortgaged=True)})
    result = reconcile(s, {"Boardwalk": obs(ME, None)}, None)
    assert result.state == s and not result.pending


# --- 家・ホテル ---


def test_matching_houses_do_not_open_the_group() -> None:
    s = state(red_monopoly(houses=3))
    result = reconcile(s, {}, {"red": GroupObservation(9.2, 0)})
    assert not result.open_groups


def test_house_difference_of_two_or_more_opens_the_group() -> None:
    s = state(red_monopoly(houses=3))  # 台帳 9 軒
    result = reconcile(s, {}, {"red": GroupObservation(11.2, 0)})
    assert result.open_groups == ("red",)
    assert result.state == s  # 台帳は書き換えない


def test_one_house_difference_is_tolerated() -> None:
    assert HOUSE_UNITS_TOLERANCE > 1.0
    s = state(red_monopoly(houses=3))
    result = reconcile(s, {}, {"red": GroupObservation(10.0, 0)})
    assert not result.open_groups


def test_a_new_hotel_opens_the_group() -> None:
    s = state(red_monopoly(houses=3))
    result = reconcile(s, {}, {"red": GroupObservation(6.0, 1)})
    assert result.open_groups == ("red",)


def test_missing_hotel_opens_the_group() -> None:
    holdings = red_monopoly(houses=4)
    holdings["Illinois Avenue"] = Holding(owner=ME, houses=5)
    result = reconcile(state(holdings), {}, {"red": GroupObservation(8.0, 0)})
    assert result.open_groups == ("red",)


def test_houses_on_a_group_nobody_monopolises_are_discarded() -> None:
    holdings = {"Kentucky Avenue": Holding(owner=ME), "Indiana Avenue": Holding(owner=AI)}
    result = reconcile(state(holdings), {}, {"red": GroupObservation(6.0, 0)})
    assert not result.open_groups
    assert any("誤読" in note for note in result.notes)


def test_unreadable_buildings_skip_the_house_check() -> None:
    result = reconcile(state(red_monopoly(houses=3)), {}, None)
    assert not result.open_groups


def test_ai_monopoly_is_also_checked() -> None:
    holdings = {name: Holding(owner=AI, houses=1) for name in RED}
    result = reconcile(state(holdings), {}, {"red": GroupObservation(7.0, 0)})
    assert result.open_groups == ("red",)


# --- 開いて読んだ家の数の反映 ---


def test_with_houses_updates_owned_tiles_only() -> None:
    s = state({"Kentucky Avenue": Holding(owner=ME, houses=1)})
    updated = with_houses(s, {"Kentucky Avenue": 3, "Indiana Avenue": 2})
    assert updated.holdings["Kentucky Avenue"].houses == 3
    assert "Indiana Avenue" not in updated.holdings
