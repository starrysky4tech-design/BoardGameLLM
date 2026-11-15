"""実機の対局の状態から、方針(ExpectedValuePolicy)に判断を問い合わせる(画面には依存しない)。

方針は、シミュレーション用の `Game` を前提に書かれている。ここでは、実機の状態(MonopolyState、位置、
刑務所)を `Game` に載せて、方針の判断だけを取り出す。方針のコードは変えない。

判断:
- 購入するか(`buy`)
- オークションの入札額(`auction_bid`): 方針の上限 `auction_limit` と、相手の現金と同額で入札する規則
  (`winning_bid`)の両方を満たす額。上限に届かなければ None(降りる)
- 建てる土地(`builds`): 方針の `manage` が建てる家の差分
- 取引の応答(`accept_trade`): 方針の `respond_to_trade`
"""

from collections.abc import Mapping
from dataclasses import dataclass, field

from bglm.plugins.monopoly.logic.auction_bid import (
    drain_bid,
    probe_bid,
    raising_bid,
    winning_bid,
)
from bglm.plugins.monopoly.logic.catalogue import CATALOGUE
from bglm.plugins.monopoly.logic.engine import Game
from bglm.plugins.monopoly.logic.funding import FundingStep, next_step
from bglm.plugins.monopoly.logic.jail import JailAction, decide_jail
from bglm.plugins.monopoly.logic.models import Deed, MonopolyState, Player, Trade
from bglm.plugins.monopoly.logic.opponent_model import BidModel
from bglm.plugins.monopoly.logic.policies import ExpectedValuePolicy, GreedyPolicy
from bglm.plugins.monopoly.logic.trade_advisor import TradeDecision, decide_trade


@dataclass(frozen=True)
class LiveState:
    """実機から読んだ(または追跡した)、いまの対局の状態。"""

    state: MonopolyState
    positions: Mapping[Player, int]
    in_jail: frozenset[Player] = frozenset()
    jail_cards: int = 0  # 自分が持つ「釈放カード」の枚数
    jail_failed: int = 0  # 自分が刑務所で、ダブルが出なかった回数
    jail_fails: Mapping[Player, int] = field(
        default_factory=dict
    )  # 刑務所にいる各プレイヤーの、ダブルが出なかった回数(建設の判断で、相手が出る確率に使う)


class Decider:
    """方針に問い合わせる。方針は 1 つで、自分(Player.SELF)として判断する。"""

    def __init__(self, policy: ExpectedValuePolicy | None = None) -> None:
        self.policy = policy or ExpectedValuePolicy()
        self.bid_model = BidModel()  # 相手の入札の上限の推定。対局中の観測で更新する
        self.policy.bid_model = self.bid_model

    def _game(self, live: LiveState) -> Game:
        game = Game({Player.SELF: self.policy, Player.AI: GreedyPolicy()})
        game.state = live.state
        for player, position in live.positions.items():
            game.position[player] = position
        for player in live.in_jail:
            game.jail_rest[player] = live.jail_fails.get(player, 0)
        return game

    def buy(self, live: LiveState, square: str) -> bool:
        """止まった土地を買うか。購入の画面で、価格が現金を超えるときは、買えないので False。"""
        deed = CATALOGUE[square]
        if deed.price > live.state.cash[Player.SELF]:
            return False
        return self.policy.wants_to_buy(self._game(live), Player.SELF, deed)

    def auction_bid(
        self, live: LiveState, square: str, highest_bid: int, first: bool = True
    ) -> int | None:
        """オークションの入札額。届かなければ None(降りる)。

        順序:
        1. 最初の入札で、相手の上限の推定が信頼でき、相手の現金と同額より安く落札できそうなら、推定のすぐ上から入札
           (`probe_bid`。外れて相手が上回ったら、次の入札は 2 へ戻る)
        2. 相手の現金と同額(落札できる最小の額。`winning_bid`)。自分の上限の範囲で
        3. 落札できないときは、相手に払わせる入札(`drain_bid`、無ければ `raising_bid`)。推定の上限を超えない
        """
        deed: Deed = CATALOGUE[square]
        game = self._game(live)
        limit = self.policy.auction_limit(game, Player.SELF, deed)
        my_cash = live.state.cash[Player.SELF]
        ai_cash = live.state.cash[Player.AI]
        model = self.bid_model
        ceiling = model.ceiling(deed.price, ai_cash)
        if first and not model.conservative:
            probe = probe_bid(highest_bid, ceiling, limit, my_cash, ai_cash)
            if probe is not None:
                return probe
        winning = winning_bid(
            highest_bid=highest_bid, opponent_cash=ai_cash, my_limit=limit, my_cash=my_cash
        )
        if winning is not None:
            return winning
        # 勝てないときは、相手に払わせる入札を重ねる
        value, _strategic = self.policy.deed_value(game, Player.SELF, deed)
        drain = drain_bid(
            highest_bid,
            ceiling,
            my_cash,
            self.policy.auction_keep(game, Player.SELF, deed),
            value,
            deed.price,
            conservative=model.conservative,
        )
        raising = raising_bid(highest_bid, limit, my_cash)
        candidates = [bid for bid in (drain, raising) if bid is not None]
        return max(candidates) if candidates else None

    def builds(self, live: LiveState) -> dict[str, int]:
        """方針が、いま建てる家。土地の名前 → 建てる軒数。"""
        game = self._game(live)
        before = {name: h.houses for name, h in game.state.holdings.items()}
        self.policy.manage(game, Player.SELF)
        return {
            name: h.houses - before.get(name, 0)
            for name, h in game.state.holdings.items()
            if h.houses > before.get(name, 0)
        }

    def jail_action(self, live: LiveState) -> JailAction:
        """刑務所の中の手番で、カードを使う・保釈金を払う・Roll して待つ、のどれか(基準は logic/jail.py)。"""
        game = self._game(live)
        return decide_jail(
            live.state,
            CATALOGUE,
            Player.SELF,
            jail_cards=live.jail_cards,
            failed_rolls=live.jail_failed,
            reserve=self.policy.reserve(game, Player.SELF),
        )

    def respond_trade(self, live: LiveState, proposer: Player, trade: Trade) -> TradeDecision:
        """相手の取引の提案への応答(受ける・断る・対案。基準は logic/trade_advisor.py)。"""
        return decide_trade(live.state, CATALOGUE, Player.SELF, proposer, trade, self.policy)

    def funds_shortfall(self, live: LiveState) -> int:
        """資金調達を始める不足額。所持金がマイナス(止まって、家賃などを払った後の負債)のときの、その額。

        先回りはしない(2026-11-08 の指示): 相手の家・ホテルに止まる前に資産を売ると、止まらなかったときに無駄になり、
        売った家の賃料も取り損ねる。止まって払うことが決まってから、足りない分だけ調達する。
        """
        return max(0, -live.state.cash[Player.SELF])

    def funding_step(
        self, live: LiveState, refused_trades: frozenset[str] = frozenset()
    ) -> FundingStep | None:
        """資金調達の、いま取る 1 手(基準は logic/funding.py)。足りていれば None。"""
        if self.funds_shortfall(live) == 0:
            return None
        return next_step(live.state, CATALOGUE, Player.SELF, refused_trades)

    def accept_trade(self, live: LiveState, proposer: Player, trade: Trade) -> bool:
        return self.policy.respond_to_trade(self._game(live), Player.SELF, proposer, trade)
