"""取引への応答(logic/trade_advisor.py)のテスト。期待値は、指示(2026-11-08)の優先順から手で作る。

取引の向き: proposer = 相手(AI)が、proposer_deeds と proposer_cash を渡し、自分が partner_deeds と
partner_cash を渡す。
"""

from bglm.plugins.monopoly.logic.catalogue import CATALOGUE
from bglm.plugins.monopoly.logic.models import Holding, MonopolyState, Player, Trade
from bglm.plugins.monopoly.logic.trade_advisor import (
    Verdict,
    complete_groups,
    decide_trade,
)

SELF, AI = Player.SELF, Player.AI


def st(holdings: dict[str, Holding], cash: int = 1000, ai_cash: int = 1000) -> MonopolyState:
    return MonopolyState(cash={SELF: cash, AI: ai_cash}, holdings=holdings)


def own(owner: Player, *names: str) -> dict[str, Holding]:
    return {n: Holding(owner=owner) for n in names}


def test_accepts_when_only_i_complete_a_group() -> None:
    # 自分が Park Place、AI が Boardwalk を持つ。AI が Boardwalk を ₼500 で渡すと、自分だけ濃青が揃う
    holdings = {**own(SELF, "Park Place"), **own(AI, "Boardwalk")}
    trade = Trade(proposer_deeds=frozenset({"Boardwalk"}), partner_cash=500)
    decision = decide_trade(st(holdings), CATALOGUE, SELF, AI, trade)
    assert decision.verdict is Verdict.ACCEPT


def test_accepts_when_my_railroad_count_goes_up_and_the_opponent_completes_nothing() -> None:
    holdings = {
        **own(SELF, "Reading Railroad"),
        **own(AI, "Pennsylvania Railroad", "Baltic Avenue"),
    }
    trade = Trade(proposer_deeds=frozenset({"Pennsylvania Railroad"}), partner_cash=100)
    decision = decide_trade(st(holdings), CATALOGUE, SELF, AI, trade)
    assert decision.verdict is Verdict.ACCEPT


def test_declines_a_deal_that_completes_my_group_at_an_absurd_price() -> None:
    holdings = {**own(SELF, "Park Place"), **own(AI, "Boardwalk")}
    trade = Trade(proposer_deeds=frozenset({"Boardwalk"}), partner_cash=1000)  # 全財産を要求される
    decision = decide_trade(st(holdings, cash=1000), CATALOGUE, SELF, AI, trade)
    assert decision.verdict is Verdict.DECLINE


def test_both_complete_accepts_when_my_group_is_better() -> None:
    # 自分: オレンジ(St. James・Tennessee)を持ち、AI が New York を持つ。AI は茶の Baltic を持ち、自分が Mediterranean を持つ。
    # 交換: 自分が Mediterranean を渡して Baltic を受け取る(AI が茶を揃える)と同時に、New York を受け取る(自分がオレンジを揃える)
    holdings = {
        **own(SELF, "St. James Place", "Tennessee Avenue", "Mediterranean Avenue"),
        **own(AI, "New York Avenue", "Baltic Avenue"),
    }
    trade = Trade(
        proposer_deeds=frozenset({"New York Avenue", "Baltic Avenue"}),
        partner_deeds=frozenset({"Mediterranean Avenue"}),
    )
    after_groups = complete_groups(
        MonopolyState(cash={SELF: 1000, AI: 1000}, holdings=holdings), CATALOGUE, SELF
    )
    assert after_groups == set()
    decision = decide_trade(st(holdings), CATALOGUE, SELF, AI, trade)
    # 自分がオレンジ、AI は Baltic だけを失い茶を持たない(AI は揃わない)ので、優先 1 で受ける
    assert decision.verdict is Verdict.ACCEPT


def test_both_complete_declines_when_the_opponents_group_is_better() -> None:
    # 自分は茶(Baltic・Mediterranean)を揃えられる取引だが、その代わりに AI がオレンジを揃える
    holdings = {
        **own(SELF, "Mediterranean Avenue", "New York Avenue"),
        **own(AI, "Baltic Avenue", "St. James Place", "Tennessee Avenue"),
    }
    trade = Trade(
        proposer_deeds=frozenset({"Baltic Avenue"}),
        partner_deeds=frozenset({"New York Avenue"}),
    )
    decision = decide_trade(st(holdings), CATALOGUE, SELF, AI, trade)
    assert decision.verdict is Verdict.DECLINE
    assert "評価" in decision.reason


def test_only_the_opponent_completes_a_group_counters_with_more_deeds() -> None:
    # AI が茶の Baltic を持ち、自分が Mediterranean を持つ。AI が 1 : 1 の交換(Mediterranean と Reading)を求める。
    # 相手だけが茶を揃える。1 枚 : 複数枚(+ お金)の対案を出す
    holdings = {
        **own(SELF, "Mediterranean Avenue"),
        **own(AI, "Baltic Avenue", "Reading Railroad", "Pennsylvania Railroad", "Vermont Avenue"),
    }
    trade = Trade(
        proposer_deeds=frozenset({"Reading Railroad"}),
        partner_deeds=frozenset({"Mediterranean Avenue"}),
    )
    decision = decide_trade(st(holdings), CATALOGUE, SELF, AI, trade)
    assert decision.verdict in (Verdict.COUNTER, Verdict.DECLINE)
    if decision.verdict is Verdict.COUNTER:
        counter = decision.counter
        assert counter is not None
        assert counter.proposer_deeds == frozenset({"Mediterranean Avenue"})  # 自分(proposer)が渡す
        assert len(counter.partner_deeds) in (2, 3)  # 相手から、2 枚か 3 枚
        assert counter.partner_cash >= 0


def test_unrelated_unfavorable_trade_is_declined() -> None:
    # 独占に関わらない。価値の低い Baltic を受け取り、価値の高い Vermont を渡す取引は、断る
    holdings = {**own(SELF, "Vermont Avenue"), **own(AI, "Baltic Avenue")}
    trade = Trade(
        proposer_deeds=frozenset({"Baltic Avenue"}), partner_deeds=frozenset({"Vermont Avenue"})
    )
    decision = decide_trade(st(holdings), CATALOGUE, SELF, AI, trade)
    assert decision.verdict is Verdict.DECLINE
