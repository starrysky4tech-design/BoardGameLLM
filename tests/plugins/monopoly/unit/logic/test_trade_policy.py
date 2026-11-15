"""取引の判断(方針)のテスト。独占を完成させる取引は積極的に、相手に独占を作らせる取引は断る。"""

from bglm.plugins.monopoly.logic.catalogue import CATALOGUE
from bglm.plugins.monopoly.logic.engine import Game
from bglm.plugins.monopoly.logic.models import Holding, MonopolyState, Player, Trade
from bglm.plugins.monopoly.logic.policies import ExpectedValuePolicy, GreedyPolicy

SELF, AI = Player.SELF, Player.AI
RED = ("Kentucky Avenue", "Indiana Avenue", "Illinois Avenue")


def game_with(
    holdings: dict[str, Holding], self_cash: int = 1500, ai_cash: int = 1500
) -> tuple[Game, ExpectedValuePolicy]:
    policy = ExpectedValuePolicy()
    game = Game({SELF: policy, AI: GreedyPolicy()})
    game.state = MonopolyState(cash={SELF: self_cash, AI: ai_cash}, holdings=holdings)
    return game, policy


def test_accepts_an_offer_that_completes_our_group_for_modest_cash() -> None:
    # 自分(SELF)が赤の 2 軒を持ち、AI が残りの 1 軒を持つ。AI が、その 1 軒を現金 300 で譲ると提案
    game, policy = game_with(
        {
            "Kentucky Avenue": Holding(owner=SELF),
            "Indiana Avenue": Holding(owner=SELF),
            "Illinois Avenue": Holding(owner=AI),
        }
    )
    offer = Trade(proposer_deeds=frozenset({"Illinois Avenue"}), partner_cash=300)
    assert policy.respond_to_trade(game, SELF, AI, offer)


def test_declines_an_offer_that_lets_the_opponent_complete_a_group() -> None:
    # AI が赤の 2 軒を持ち、自分が残りの 1 軒を持つ。AI が、その 1 軒を安く買い取ると提案
    game, policy = game_with(
        {
            "Kentucky Avenue": Holding(owner=AI),
            "Indiana Avenue": Holding(owner=AI),
            "Illinois Avenue": Holding(owner=SELF),
        }
    )
    offer = Trade(
        partner_deeds=frozenset({"Illinois Avenue"}), proposer_cash=260
    )  # 定価 240 より高い
    assert not policy.respond_to_trade(game, SELF, AI, offer)


def test_declines_a_plain_swap_with_no_gain() -> None:
    game, policy = game_with(
        {"Reading Railroad": Holding(owner=SELF), "Short Line": Holding(owner=AI)}
    )
    offer = Trade(
        proposer_deeds=frozenset({"Short Line"}), partner_deeds=frozenset({"Reading Railroad"})
    )
    assert not policy.respond_to_trade(game, SELF, AI, offer)


def test_proposes_buying_the_deed_that_completes_our_group_cheapest_first() -> None:
    game, policy = game_with(
        {
            "Kentucky Avenue": Holding(owner=SELF),
            "Indiana Avenue": Holding(owner=SELF),
            "Illinois Avenue": Holding(owner=AI),
        }
    )
    offers = policy.propose_trades(game, SELF)
    assert offers
    cash = [o.proposer_cash for o in offers]
    assert cash == sorted(cash)
    assert all(o.partner_deeds == frozenset({"Illinois Avenue"}) for o in offers)


def test_no_proposal_when_no_group_can_be_completed() -> None:
    game, policy = game_with(
        {"Kentucky Avenue": Holding(owner=SELF), "Indiana Avenue": Holding(owner=AI)}
    )
    assert policy.propose_trades(game, SELF) == []


def test_trade_can_be_switched_off() -> None:
    game, _ = game_with(
        {
            "Kentucky Avenue": Holding(owner=SELF),
            "Indiana Avenue": Holding(owner=SELF),
            "Illinois Avenue": Holding(owner=AI),
        }
    )
    off = ExpectedValuePolicy(trade=False)
    assert off.propose_trades(game, SELF) == []
    offer = Trade(proposer_deeds=frozenset({"Illinois Avenue"}), partner_cash=300)
    assert not off.respond_to_trade(game, SELF, AI, offer)


def test_the_greedy_baseline_accepts_a_trade_that_is_not_worse_in_list_price() -> None:
    game = Game({SELF: ExpectedValuePolicy(), AI: GreedyPolicy()})
    game.state = MonopolyState(
        cash={SELF: 1500, AI: 1500}, holdings={"Illinois Avenue": Holding(owner=AI)}
    )
    greedy = GreedyPolicy()
    at_list = Trade(partner_deeds=frozenset({"Illinois Avenue"}), proposer_cash=240)
    below_list = Trade(partner_deeds=frozenset({"Illinois Avenue"}), proposer_cash=200)
    assert greedy.respond_to_trade(game, AI, SELF, at_list)
    assert not greedy.respond_to_trade(game, AI, SELF, below_list)


def test_auction_limit_never_exceeds_the_list_price() -> None:
    # 実機(2026-11-01): 相手は M22 だけ。States Avenue(定価 140)は、相手の +1 の M23 で取れる範囲
    game, policy = game_with({}, self_cash=948, ai_cash=22)
    states = CATALOGUE["States Avenue"]
    limit = policy.auction_limit(game, SELF, states)
    assert 23 <= limit <= states.price


def test_a_deed_that_completes_our_group_may_go_above_the_list_price() -> None:
    # 赤のグループを 2 軒持つ。Illinois(定価 240)を取ると独占が完成するので、定価を超えて入札してよい
    game, policy = game_with(
        {"Kentucky Avenue": Holding(owner=SELF), "Indiana Avenue": Holding(owner=SELF)},
        self_cash=1500,
        ai_cash=1500,
    )
    illinois = CATALOGUE["Illinois Avenue"]
    assert policy.auction_limit(game, SELF, illinois) > illinois.price


def test_drops_out_when_the_needed_bid_is_above_the_limit() -> None:
    # 相手の現金が多く、定価を超えないと勝てない: 上限は定価までなので、降りる(入札しない)
    game, policy = game_with({}, self_cash=948, ai_cash=500)
    states = CATALOGUE["States Avenue"]
    assert policy.auction_limit(game, SELF, states) <= states.price < 501


def test_does_not_bid_above_the_reserve_to_beat_a_poor_opponent() -> None:
    game, policy = game_with({}, self_cash=100, ai_cash=22)
    states = CATALOGUE["States Avenue"]
    assert policy.auction_limit(game, SELF, states) <= 100 - policy.reserve_min


def test_the_engine_executes_an_accepted_proposal() -> None:
    game, policy = game_with(
        {
            "Kentucky Avenue": Holding(owner=SELF),
            "Indiana Avenue": Holding(owner=SELF),
            "Illinois Avenue": Holding(owner=AI),
        }
    )
    offers = policy.propose_trades(game, SELF)
    assert any(game.try_trade(SELF, offer) for offer in offers)
    assert game.state.holdings["Illinois Avenue"].owner is SELF
