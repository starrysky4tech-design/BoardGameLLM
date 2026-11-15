"""妨害価値のテスト。2026-11-08 の対局: ピンクを見送り、AI に揃えさせて負けた。"""

from bglm.plugins.monopoly.logic.catalogue import CATALOGUE
from bglm.plugins.monopoly.logic.engine import Game
from bglm.plugins.monopoly.logic.models import Holding, MonopolyState, Player
from bglm.plugins.monopoly.logic.policies import ExpectedValuePolicy, GreedyPolicy

SELF, AI = Player.SELF, Player.AI


def game_with(holdings: dict[str, Holding], cash: int = 800) -> tuple[Game, ExpectedValuePolicy]:
    policy = ExpectedValuePolicy()
    game = Game({SELF: policy, AI: GreedyPolicy()})
    game.state = MonopolyState(cash={SELF: cash, AI: 1500}, holdings=holdings)
    return game, policy


def test_buys_first_pink_at_list_price_when_unowned() -> None:
    game, policy = game_with({})
    assert policy.wants_to_buy(game, SELF, CATALOGUE["Virginia Avenue"])


def test_buys_pink_when_opponent_holds_one() -> None:
    game, policy = game_with({"St. Charles Place": Holding(owner=AI)})
    deed = CATALOGUE["Virginia Avenue"]
    value, _ = policy.deed_value(game, SELF, deed)
    assert value > deed.price
    assert policy.wants_to_buy(game, SELF, deed)


def test_deny_value_scales_with_opponent_share() -> None:
    one, policy = game_with({"St. Charles Place": Holding(owner=AI)})
    two, _ = game_with({"St. Charles Place": Holding(owner=AI), "States Avenue": Holding(owner=AI)})
    deed = CATALOGUE["Virginia Avenue"]
    assert policy.deed_value(two, SELF, deed)[0] > policy.deed_value(one, SELF, deed)[0]
