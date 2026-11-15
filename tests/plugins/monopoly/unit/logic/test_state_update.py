"""Log の出来事から、所有・家・抵当の状態への反映(logic/state_update.py)のテスト。期待値は手で書く。"""

from bglm.plugins.monopoly.logic import events as ev
from bglm.plugins.monopoly.logic.models import Holding, MonopolyState, Player
from bglm.plugins.monopoly.logic.state_update import apply_events

SELF, AI = Player.SELF, Player.AI


def base(**holdings: Holding) -> MonopolyState:
    return MonopolyState(
        cash={SELF: 1000, AI: 100}, holdings={k.replace("_", " "): v for k, v in holdings.items()}
    )


def test_auction_win_gives_the_property_to_the_winner_once() -> None:
    events: list[ev.LogEvent] = [
        ev.AuctionWon(SELF, "St. James Place", 65),
        ev.AuctionWon(SELF, "St. James Place", None),  # 同じ落札の 2 行目(金額なし)
    ]
    update = apply_events(base(), events)
    assert update.state.holdings["St. James Place"] == Holding(owner=SELF)
    assert update.unhandled == []


def test_houses_built_and_sold() -> None:
    state = base(Baltic_Avenue=Holding(owner=AI, houses=2))
    update = apply_events(
        state, [ev.HousesBuilt(AI, 1, "Baltic Avenue"), ev.HousesSold(AI, 1, "Baltic Avenue")]
    )
    assert update.state.holdings["Baltic Avenue"].houses == 2
    update = apply_events(state, [ev.HousesSold(AI, 5, "Baltic Avenue")])
    assert update.state.holdings["Baltic Avenue"].houses == 0  # 下限


def test_houses_are_capped_at_the_hotel_level() -> None:
    state = base(Baltic_Avenue=Holding(owner=AI, houses=4))
    update = apply_events(state, [ev.HousesBuilt(AI, 3, "Baltic Avenue")])
    assert update.state.holdings["Baltic Avenue"].houses == 5


def test_mortgage_marks_the_holding() -> None:
    state = base(Illinois_Avenue=Holding(owner=AI))
    update = apply_events(state, [ev.Mortgaged(AI, "Illinois Avenue", 120)])
    assert update.state.holdings["Illinois Avenue"].mortgaged is True


def test_contradictions_are_reported_not_applied() -> None:
    # 所有者でない側が、家を建てた・抵当に入れた、はあり得ない。状態を変えず、報告する
    state = base(Baltic_Avenue=Holding(owner=AI))
    update = apply_events(
        state, [ev.HousesBuilt(SELF, 1, "Baltic Avenue"), ev.Mortgaged(SELF, "Baltic Avenue", 30)]
    )
    assert update.state.holdings["Baltic Avenue"] == Holding(owner=AI)
    assert len(update.unhandled) == 2


def test_auction_win_on_an_owned_property_is_reported() -> None:
    state = base(Boardwalk=Holding(owner=AI))
    update = apply_events(state, [ev.AuctionWon(SELF, "Boardwalk", 155)])
    assert update.state.holdings["Boardwalk"] == Holding(owner=AI)
    assert update.unhandled


def test_cash_is_untouched() -> None:
    state = base()
    assert apply_events(state, [ev.AuctionWon(SELF, "Boardwalk", 155)]).state.cash == state.cash


def test_hotel_sets_the_hotel_level() -> None:
    state = base(Baltic_Avenue=Holding(owner=AI, houses=4))
    update = apply_events(state, [ev.HotelBuilt(AI, "Baltic Avenue")])
    assert update.state.holdings["Baltic Avenue"].houses == 5 and update.unhandled == []
