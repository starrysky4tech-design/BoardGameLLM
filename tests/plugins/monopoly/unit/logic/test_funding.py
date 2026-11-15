"""資金調達の順序(logic/funding.py)のテスト。期待値は、指示(2026-11-08)の優先順から手で作る。"""

from bglm.plugins.monopoly.logic.catalogue import CATALOGUE
from bglm.plugins.monopoly.logic.funding import StepKind, next_step, plan
from bglm.plugins.monopoly.logic.models import Holding, MonopolyState, Player

SELF, AI = Player.SELF, Player.AI


def st(cash: int, holdings: dict[str, Holding], ai_cash: int = 500) -> MonopolyState:
    return MonopolyState(cash={SELF: cash, AI: ai_cash}, holdings=holdings)


def test_first_mortgage_the_cheapest_street_of_an_incomplete_group() -> None:
    holdings = {
        "Vermont Avenue": Holding(owner=SELF),  # ライトブルー(揃っていない)
        "Baltic Avenue": Holding(owner=SELF),  # 茶(揃っていない)。定価 60 で一番安い
        "Reading Railroad": Holding(owner=SELF),
    }
    step = next_step(st(0, holdings), CATALOGUE, SELF)
    assert step is not None and step.kind is StepKind.MORTGAGE and step.name == "Baltic Avenue"
    assert step.gain == CATALOGUE["Baltic Avenue"].mortgage


def test_a_complete_group_is_not_mortgaged_first() -> None:
    holdings = {
        "Baltic Avenue": Holding(owner=SELF),
        "Mediterranean Avenue": Holding(owner=SELF),  # 茶が揃っている
        "Reading Railroad": Holding(owner=SELF),
    }
    step = next_step(st(0, holdings), CATALOGUE, SELF)
    assert step is not None and step.name == "Reading Railroad"  # 次は、鉄道・会社


def test_then_the_railroad_or_utility_with_lower_income() -> None:
    holdings = {
        "Water Works": Holding(owner=SELF),
        "Reading Railroad": Holding(owner=SELF),
        "Pennsylvania Railroad": Holding(owner=SELF),
    }
    step = next_step(st(0, holdings), CATALOGUE, SELF)
    assert (
        step is not None and step.name == "Water Works"
    )  # 会社 1 つ(賃料の目安 28)が、鉄道 2 つより低い


def test_then_trade_the_mortgaged_deeds_while_keeping_them_mortgaged() -> None:
    holdings = {
        "Baltic Avenue": Holding(owner=SELF, mortgaged=True),
        "Mediterranean Avenue": Holding(
            owner=SELF
        ),  # 茶が揃っている(Baltic が抵当中でも、先には抵当に入れない)
    }
    step = next_step(st(0, holdings, ai_cash=500), CATALOGUE, SELF)
    assert step is not None
    assert step.kind is StepKind.MORTGAGE or step.kind is StepKind.TRADE_MORTGAGED
    # 揃っていた茶は、Baltic が抵当中でも「揃っている」。残りの Mediterranean は、先に取引の手が来ない
    refused = frozenset({"Baltic Avenue"})
    again = next_step(st(0, holdings, 500), CATALOGUE, SELF, refused_trades=refused)
    assert again is None or again.kind is not StepKind.TRADE_MORTGAGED


def test_trade_of_a_mortgaged_railroad_comes_after_mortgaging() -> None:
    holdings = {"Reading Railroad": Holding(owner=SELF, mortgaged=True)}
    step = next_step(st(0, holdings, ai_cash=500), CATALOGUE, SELF)
    assert step is not None and step.kind is StepKind.TRADE_MORTGAGED
    assert (
        step.trade is not None
        and 0 < step.trade.partner_cash <= CATALOGUE["Reading Railroad"].mortgage
    )


def test_then_sell_houses_from_the_group_with_the_lowest_evaluation() -> None:
    # 茶(評価が最も低い)とオレンジ(高い)の両方に家 1 軒ずつ。先に茶の家を売る
    holdings = {
        "Baltic Avenue": Holding(owner=SELF, houses=1),
        "Mediterranean Avenue": Holding(owner=SELF, houses=1),
        "St. James Place": Holding(owner=SELF, houses=1),
        "Tennessee Avenue": Holding(owner=SELF, houses=1),
        "New York Avenue": Holding(owner=SELF, houses=1),
    }
    step = next_step(st(0, holdings, ai_cash=0), CATALOGUE, SELF)
    assert step is not None and step.kind is StepKind.SELL_HOUSE
    assert CATALOGUE[step.name].group == "brown"


def test_plan_stops_when_enough_cash_is_raised() -> None:
    holdings = {
        "Baltic Avenue": Holding(owner=SELF),
        "Vermont Avenue": Holding(owner=SELF),
        "Reading Railroad": Holding(owner=SELF),
    }
    steps = plan(st(0, holdings), CATALOGUE, SELF, needed=60)
    assert [s.name for s in steps] == [
        "Baltic Avenue",
        "Vermont Avenue",
    ]  # 30 + 50 ≥ 60 で、鉄道には進まない
