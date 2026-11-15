"""Monopoly のルールの単体テスト。期待値は、実機で読んだ金額(購入、抵当、支払いの画面)から作る。

カタログに無い土地(2 倍の賃料、鉄道の数、会社の数)は、テスト内で作った定義で確かめる。
"""

import pytest

from bglm.plugins.monopoly.logic.catalogue import CATALOGUE
from bglm.plugins.monopoly.logic.models import (
    Deed,
    DeedKind,
    Holding,
    MonopolyState,
    Player,
    Trade,
)
from bglm.plugins.monopoly.logic.rules import (
    apply_trade,
    build,
    buy,
    can_build,
    can_sell_house,
    can_trade,
    is_insolvent,
    land,
    mortgage,
    net_worth,
    owns_full_group,
    pass_go,
    pay_bank,
    rent_due,
    sell_house,
    unmortgage,
)

SELF, AI = Player.SELF, Player.AI


def game(
    self_cash: int = 1500,
    ai_cash: int = 1500,
    holdings: dict[str, Holding] | None = None,
) -> MonopolyState:
    return MonopolyState(
        cash={SELF: self_cash, AI: ai_cash},
        holdings=holdings or {},
    )


def street(name: str, group: str, size: int) -> Deed:
    return Deed(
        name=name,
        kind=DeedKind.STREET,
        group=group,
        group_size=size,
        price=60,
        mortgage=30,
        rent=(2, 10, 30, 90, 160, 250),
        house_cost=50,
    )


def railroads(count: int) -> dict[str, Deed]:
    return {
        f"RR{i}": Deed(
            name=f"RR{i}",
            kind=DeedKind.RAILROAD,
            group="railroad",
            group_size=4,
            price=200,
            mortgage=100,
            rent=(25, 50, 100, 200),
        )
        for i in range(1, count + 1)
    }


def utilities(count: int) -> dict[str, Deed]:
    return {
        f"UT{i}": Deed(
            name=f"UT{i}",
            kind=DeedKind.UTILITY,
            group="utility",
            group_size=2,
            price=150,
            mortgage=75,
        )
        for i in range(1, count + 1)
    }


# --- 定義(実機で確かめた値) ---


def test_catalogue_matches_the_values_seen_on_the_screen() -> None:
    kentucky = CATALOGUE["Kentucky Avenue"]
    assert (kentucky.price, kentucky.mortgage) == (220, 110)  # 購入と抵当の画面
    assert kentucky.rent == (18, 90, 250, 700, 875, 1050)
    assert CATALOGUE["Indiana Avenue"].rent[0] == 18  # AI に払った 18
    st_charles = CATALOGUE["St. Charles Place"]
    assert (st_charles.price, st_charles.mortgage) == (140, 70)
    assert CATALOGUE["Electric Company"].mortgage == 75


def test_deed_rent_length_is_checked() -> None:
    with pytest.raises(ValueError):
        Deed(
            name="bad",
            kind=DeedKind.STREET,
            group="g",
            group_size=2,
            price=60,
            mortgage=30,
            rent=(2, 10, 30),
        )


# --- 賃料 ---


def test_street_rent_is_the_base_rent_without_houses() -> None:
    # 実機: AI の Indiana Avenue に止まり、18 を払った
    state = game(holdings={"Indiana Avenue": Holding(owner=AI)})
    assert rent_due(state, CATALOGUE, "Indiana Avenue", 3) == 18


def test_street_rent_doubles_when_the_owner_has_the_full_group() -> None:
    catalogue = {"A": street("A", "g", 2), "B": street("B", "g", 2)}
    state = game(holdings={"A": Holding(owner=AI), "B": Holding(owner=AI)})
    assert owns_full_group(state, catalogue, AI, catalogue["A"])
    assert rent_due(state, catalogue, "A", 5) == 4  # 基本 2 × 2


def test_group_is_not_full_when_one_deed_is_missing() -> None:
    catalogue = {"A": street("A", "g", 2), "B": street("B", "g", 2)}
    state = game(holdings={"A": Holding(owner=AI)})
    assert rent_due(state, catalogue, "A", 5) == 2


def test_houses_replace_the_base_rent() -> None:
    state = game(holdings={"Kentucky Avenue": Holding(owner=AI, houses=2)})
    assert rent_due(state, CATALOGUE, "Kentucky Avenue", 5) == 250


def test_hotel_rent() -> None:
    state = game(holdings={"Kentucky Avenue": Holding(owner=AI, houses=5)})
    assert rent_due(state, CATALOGUE, "Kentucky Avenue", 5) == 1050


def test_mortgaged_deed_collects_no_rent() -> None:
    state = game(holdings={"Kentucky Avenue": Holding(owner=AI, mortgaged=True)})
    assert rent_due(state, CATALOGUE, "Kentucky Avenue", 5) == 0
    after, paid = land(state, CATALOGUE, SELF, "Kentucky Avenue", 5)
    assert paid == 0 and after == state


def test_railroad_rent_follows_the_number_owned() -> None:
    catalogue = railroads(4)
    expected = {1: 25, 2: 50, 3: 100, 4: 200}
    for owned, rent in expected.items():
        holdings = {f"RR{i}": Holding(owner=AI) for i in range(1, owned + 1)}
        assert rent_due(game(holdings=holdings), catalogue, "RR1", 7) == rent


def test_utility_rent_is_dice_times_4_or_10() -> None:
    catalogue = utilities(2)
    one = game(holdings={"UT1": Holding(owner=AI)})
    assert rent_due(one, catalogue, "UT1", 7) == 28
    two = game(holdings={"UT1": Holding(owner=AI), "UT2": Holding(owner=AI)})
    assert rent_due(two, catalogue, "UT1", 7) == 70


def test_dice_out_of_range_is_rejected_for_utilities() -> None:
    catalogue = utilities(1)
    state = game(holdings={"UT1": Holding(owner=AI)})
    with pytest.raises(ValueError):
        rent_due(state, catalogue, "UT1", 13)


def test_no_rent_on_own_or_unowned_deed() -> None:
    own = game(holdings={"Kentucky Avenue": Holding(owner=SELF)})
    assert land(own, CATALOGUE, SELF, "Kentucky Avenue", 5) == (own, 0)
    free = game()
    assert land(free, CATALOGUE, SELF, "Kentucky Avenue", 5) == (free, 0)


def test_landing_on_an_owned_deed_moves_the_rent_to_the_owner() -> None:
    state = game(self_cash=37, holdings={"Indiana Avenue": Holding(owner=AI)})
    after, paid = land(state, CATALOGUE, SELF, "Indiana Avenue", 3)
    assert paid == 18
    assert after.cash == {SELF: 19, AI: 1518}


# --- 購入 ---


def test_buy_moves_the_price_and_sets_the_owner() -> None:
    state = buy(game(), CATALOGUE, SELF, "Kentucky Avenue")
    assert state.cash[SELF] == 1280
    assert state.holdings["Kentucky Avenue"].owner is SELF


def test_buy_rejects_insufficient_cash() -> None:
    with pytest.raises(ValueError):
        buy(game(self_cash=100), CATALOGUE, SELF, "Kentucky Avenue")


def test_buy_rejects_an_owned_deed() -> None:
    state = game(holdings={"Kentucky Avenue": Holding(owner=AI)})
    with pytest.raises(ValueError):
        buy(state, CATALOGUE, SELF, "Kentucky Avenue")


# --- 抵当 ---


def test_mortgage_pays_the_mortgage_value() -> None:
    state = game(self_cash=87, holdings={"Kentucky Avenue": Holding(owner=SELF)})
    after = mortgage(state, CATALOGUE, SELF, "Kentucky Avenue")
    assert after.cash[SELF] == 87 + 110  # 実機: 抵当価値 110
    assert after.holdings["Kentucky Avenue"].mortgaged


def test_mortgage_rejects_a_deed_with_houses() -> None:
    state = game(holdings={"Kentucky Avenue": Holding(owner=SELF, houses=1)})
    with pytest.raises(ValueError):
        mortgage(state, CATALOGUE, SELF, "Kentucky Avenue")


def test_mortgage_rejects_another_players_deed() -> None:
    state = game(holdings={"Kentucky Avenue": Holding(owner=AI)})
    with pytest.raises(ValueError):
        mortgage(state, CATALOGUE, SELF, "Kentucky Avenue")


# --- GO と支払い ---


def test_pass_go_collects_the_salary() -> None:
    assert pass_go(game(), SELF).cash[SELF] == 1700


def test_bank_payment_may_go_negative() -> None:
    # 実機: 残高 27 から 50 を払い、-23 になった
    state = pay_bank(game(self_cash=27), SELF, 50)
    assert state.cash[SELF] == -23
    assert is_insolvent(state, SELF)
    assert not is_insolvent(game(), SELF)


# --- 建設・売却・抵当の解除(ご指示の規則) ---


def red_group(owner: Player = SELF, houses: tuple[int, int, int] = (0, 0, 0)) -> MonopolyState:
    names = ("Kentucky Avenue", "Indiana Avenue", "Illinois Avenue")
    return game(
        holdings={n: Holding(owner=owner, houses=h) for n, h in zip(names, houses, strict=True)}
    )


def test_build_needs_the_full_group() -> None:
    state = game(holdings={"Kentucky Avenue": Holding(owner=SELF)})
    with pytest.raises(ValueError):
        build(state, CATALOGUE, SELF, "Kentucky Avenue")


def test_build_evenly_across_the_group() -> None:
    # (0,0,1)→(0,1,1)→(1,1,1)→(1,2,1) の順は可。(0,0,2) や (0,1,2) は不可
    state = red_group(houses=(0, 0, 1))
    assert not can_build(state, CATALOGUE, SELF, "Illinois Avenue")  # すでに 1 軒。(0,0,2) になる
    assert can_build(state, CATALOGUE, SELF, "Kentucky Avenue")
    state = build(state, CATALOGUE, SELF, "Kentucky Avenue")  # (1,0,1)
    assert not can_build(state, CATALOGUE, SELF, "Kentucky Avenue")
    state = build(state, CATALOGUE, SELF, "Indiana Avenue")  # (1,1,1)
    assert can_build(
        state, CATALOGUE, SELF, "Illinois Avenue"
    )  # (1,1,2) は、偏りなしの規則に反しない
    assert can_build(state, CATALOGUE, SELF, "Kentucky Avenue")


def test_build_costs_one_house_and_hotel_replaces_four_houses() -> None:
    state = red_group(houses=(4, 4, 4))
    after = build(state, CATALOGUE, SELF, "Kentucky Avenue")  # ホテル
    assert after.holdings["Kentucky Avenue"].houses == 5
    assert after.cash[SELF] == 1500 - 150  # 家 1 軒分の費用
    # ほかの 2 軒に 4 軒ずつ無いと、ホテルは建てられない
    uneven = red_group(houses=(4, 3, 4))
    assert not can_build(uneven, CATALOGUE, SELF, "Kentucky Avenue")


def test_build_is_blocked_when_a_deed_in_the_group_is_mortgaged() -> None:
    state = red_group()
    holdings = dict(state.holdings)
    holdings["Illinois Avenue"] = Holding(owner=SELF, mortgaged=True)
    state = MonopolyState(cash=state.cash, holdings=holdings)
    assert not can_build(state, CATALOGUE, SELF, "Kentucky Avenue")


def test_sell_houses_evenly_and_get_half_the_cost() -> None:
    state = red_group(houses=(2, 2, 1))
    assert not can_sell_house(state, CATALOGUE, SELF, "Illinois Avenue")  # 最も多い土地から売る
    after = sell_house(state, CATALOGUE, SELF, "Kentucky Avenue")
    assert after.cash[SELF] == 1500 + 75  # 建設費 150 の半額
    assert after.holdings["Kentucky Avenue"].houses == 1


def test_selling_a_house_returns_other_hotels_to_four_houses() -> None:
    # 実機の確認(2026-11-01): 家 4 軒の土地を売ると、ほかの 2 軒のホテルも家 4 軒に戻り、
    # 3 件分の売却額(赤は建設費 150 の半額 75)を受け取る
    state = red_group(houses=(4, 5, 5))
    assert can_sell_house(state, CATALOGUE, SELF, "Kentucky Avenue")
    after = sell_house(state, CATALOGUE, SELF, "Kentucky Avenue")
    assert after.cash[SELF] == 1500 + 75 * 3
    names = ("Kentucky Avenue", "Indiana Avenue", "Illinois Avenue")
    assert [after.holdings[n].houses for n in names] == [3, 4, 4]


def test_a_hotel_sells_back_to_four_houses_when_the_group_has_four() -> None:
    state = red_group(houses=(4, 4, 5))
    assert can_sell_house(state, CATALOGUE, SELF, "Illinois Avenue")
    after = sell_house(state, CATALOGUE, SELF, "Illinois Avenue")
    assert after.holdings["Illinois Avenue"].houses == 4
    assert after.cash[SELF] == 1500 + 75


def test_unmortgage_costs_ten_percent_more() -> None:
    state = game(self_cash=500, holdings={"Kentucky Avenue": Holding(owner=SELF, mortgaged=True)})
    after = unmortgage(state, CATALOGUE, SELF, "Kentucky Avenue")
    assert after.cash[SELF] == 500 - 121  # 抵当価値 110 + 1 割
    assert not after.holdings["Kentucky Avenue"].mortgaged


def test_net_worth_counts_cash_deeds_and_houses() -> None:
    state = game(
        self_cash=100,
        holdings={
            "Kentucky Avenue": Holding(owner=SELF, houses=2),
            "Indiana Avenue": Holding(owner=SELF, mortgaged=True),
        },
    )
    assert net_worth(state, CATALOGUE, SELF) == 100 + 220 + 2 * 150 + 110


# --- 取引 ---


def test_trade_swaps_deeds_and_cash() -> None:
    state = game(
        holdings={"Kentucky Avenue": Holding(owner=SELF), "Indiana Avenue": Holding(owner=AI)}
    )
    trade = Trade(
        proposer_deeds=frozenset({"Kentucky Avenue"}),
        proposer_cash=50,
        partner_deeds=frozenset({"Indiana Avenue"}),
        partner_cash=0,
    )
    after = apply_trade(state, CATALOGUE, SELF, AI, trade)
    assert after.holdings["Kentucky Avenue"].owner is AI
    assert after.holdings["Indiana Avenue"].owner is SELF
    assert after.cash == {SELF: 1450, AI: 1550}


def test_trade_rejects_a_deed_the_giver_does_not_own() -> None:
    state = game(holdings={"Kentucky Avenue": Holding(owner=AI)})
    trade = Trade(proposer_deeds=frozenset({"Kentucky Avenue"}))
    with pytest.raises(ValueError):
        apply_trade(state, CATALOGUE, SELF, AI, trade)


def test_trade_rejects_cash_beyond_the_balance_and_empty_trades() -> None:
    state = game(self_cash=100)
    assert not can_trade(state, CATALOGUE, SELF, AI, Trade(proposer_cash=200))
    assert not can_trade(state, CATALOGUE, SELF, AI, Trade())


def test_trade_rejects_deeds_in_a_group_with_houses() -> None:
    state = red_group(owner=AI, houses=(1, 0, 0))
    trade = Trade(partner_deeds=frozenset({"Illinois Avenue"}), proposer_cash=500)
    assert not can_trade(state, CATALOGUE, SELF, AI, trade)  # グループに家がある


def test_receiving_a_mortgaged_deed_costs_ten_percent_interest() -> None:
    state = game(holdings={"Kentucky Avenue": Holding(owner=AI, mortgaged=True)})
    trade = Trade(partner_deeds=frozenset({"Kentucky Avenue"}), proposer_cash=100)
    after = apply_trade(state, CATALOGUE, SELF, AI, trade)
    assert after.cash[SELF] == 1500 - 100 - 11  # 抵当価値 110 の 1 割
    assert after.holdings["Kentucky Avenue"].mortgaged
