"""Monopoly の模擬エンジン。手番の流れを、2 人のプレイヤーの方針(Policy)で最後まで進める。

画面には依存しない。戦略の評価(自己対戦)に使う。ルールの出典は LOGIC_SPEC.md と RULES.md:
- 2 個のサイコロの合計で進む。ゾロ目は、もう一度振る(3 回続くと刑務所)
- 刑務所: ゾロ目なら M50 を払って出て、出た目だけ進む(続けて振れない)。3 回休んだら M50 を払い、
  JUST VISITING(10)に出る。釈放カードは無料で出る
- 購入を見送る(買えない)と、オークション。残高が負になったら、抵当と家の売却で不足を作り、
  それでも足りなければ破産(2 人対局なので、相手の勝ち)
簡略化: 取引、家の個数の上限、刑務所での罰金の先払いは扱わない。
"""

import random
from collections.abc import Callable, Mapping
from typing import Protocol

from bglm.plugins.monopoly.logic import rules
from bglm.plugins.monopoly.logic.board import (
    BOARD,
    BOARD_SIZE,
    JAIL_FINE,
    JAIL_MAX_FAILS,
    JAIL_POSITION,
    RAILROADS,
    UTILITIES,
    SquareKind,
    next_position,
)
from bglm.plugins.monopoly.logic.cards import (
    CHANCE_CARDS,
    COMMUNITY_CHEST_CARDS,
    Card,
    CardKind,
    Deck,
)
from bglm.plugins.monopoly.logic.catalogue import CATALOGUE
from bglm.plugins.monopoly.logic.models import (
    HOTEL_LEVEL,
    Deed,
    DeedKind,
    Holding,
    MonopolyState,
    Player,
    Trade,
)

START_CASH = 1500  # 実機で確かめた開始時の所持金
MAX_JAIL_REST = JAIL_MAX_FAILS
MAX_CARD_DEPTH = 4  # カードで動いた先がまたカードのマス、という連鎖の上限
MAX_TRADE_OFFERS = 8  # 1 手番に試す取引の提案の上限


class Policy(Protocol):
    def wants_to_buy(self, game: "Game", player: Player, deed: Deed) -> bool: ...

    def auction_limit(self, game: "Game", player: Player, deed: Deed) -> int:
        """オークションで、この額まで入札する(上限)。0 なら参加しない。"""
        ...

    def manage(self, game: "Game", player: Player) -> None:
        """手番の最初の管理: 抵当の解除、家の建設。"""
        ...

    def propose_trades(self, game: "Game", player: Player) -> list[Trade]:
        """この手番に持ちかける取引の候補(優先順)。エンジンが、受け入れられるまで順に試す。"""
        ...

    def respond_to_trade(
        self, game: "Game", player: Player, proposer: Player, trade: Trade
    ) -> bool:
        """相手からの取引の提案を受けるか。player は、提案された側。"""
        ...


Dice = Callable[[], tuple[int, int]]


class Game:
    def __init__(
        self,
        policies: Mapping[Player, Policy],
        seed: int = 0,
        *,
        catalogue: Mapping[str, Deed] = CATALOGUE,
        dice: Dice | None = None,
        chance_order: list[Card] | None = None,
        chest_order: list[Card] | None = None,
        first: Player = Player.SELF,
        record: bool = False,
    ) -> None:
        self.catalogue = catalogue
        self.rng = random.Random(seed)
        self.policies = dict(policies)
        self.state = MonopolyState(cash={p: START_CASH for p in Player})
        self.position = {p: 0 for p in Player}
        self.jail_rest: dict[Player, int | None] = {p: None for p in Player}  # None: 刑務所の外
        self.jail_cards: dict[Player, list[str]] = {
            p: [] for p in Player
        }  # 持っている釈放カードの山の名前
        self.decks = {
            "chance": Deck(CHANCE_CARDS, self.rng, chance_order),
            "chest": Deck(COMMUNITY_CHEST_CARDS, self.rng, chest_order),
        }
        self._dice: Dice = dice or self._random_dice
        self.current = first
        self.turns = 0  # 終えた手番の数(両者の合計)
        self.winner: Player | None = None
        self.decided_by_cap = False
        self.record = record
        self.events: list[str] = []

    # --- 補助 ---

    def _random_dice(self) -> tuple[int, int]:
        return self.rng.randint(1, 6), self.rng.randint(1, 6)

    def _note(self, message: str) -> None:
        if self.record:
            self.events.append(message)

    def cash(self, player: Player) -> int:
        return self.state.cash[player]

    # --- 方針が使う操作 ---

    def can_build(self, player: Player, name: str) -> bool:
        return rules.can_build(self.state, self.catalogue, player, name)

    def build(self, player: Player, name: str) -> None:
        self.state = rules.build(self.state, self.catalogue, player, name)
        self._note(f"{player.value} が {name} に家を建てた")

    def try_trade(self, proposer: Player, trade: Trade) -> bool:
        """取引を持ちかける。成立する(条件を満たし、相手が受ける)なら実行して True。"""
        partner = proposer.other()
        if not rules.can_trade(self.state, self.catalogue, proposer, partner, trade):
            return False
        if not self.policies[partner].respond_to_trade(self, partner, proposer, trade):
            return False
        self.state = rules.apply_trade(self.state, self.catalogue, proposer, partner, trade)
        self._note(
            f"取引成立: {proposer.value} が {sorted(trade.proposer_deeds)} と現金 {trade.proposer_cash}、"
            f"{partner.value} が {sorted(trade.partner_deeds)} と現金 {trade.partner_cash}"
        )
        return True

    def unmortgage(self, player: Player, name: str) -> None:
        self.state = rules.unmortgage(self.state, self.catalogue, player, name)
        self._note(f"{player.value} が {name} の抵当を解除")

    # --- 進行 ---

    def run(self, max_turns: int = 800) -> Player:
        """決着(破産)まで進める。上限に達したら、純資産の大きい方を勝ちとする。"""
        while self.winner is None and self.turns < max_turns:
            self.play_turn()
        if self.winner is None:
            self.decided_by_cap = True
            worth = {p: rules.net_worth(self.state, self.catalogue, p) for p in Player}
            self.winner = Player.SELF if worth[Player.SELF] >= worth[Player.AI] else Player.AI
        return self.winner

    def play_turn(self) -> None:
        player = self.current
        self.policies[player].manage(self, player)
        for offer in self.policies[player].propose_trades(self, player)[:MAX_TRADE_OFFERS]:
            if self.try_trade(player, offer):
                self.policies[player].manage(self, player)  # 取引で独占が完成したら、すぐ建てる
                break
        if self.jail_rest[player] is not None:
            self._jail_turn(player)
        else:
            self._normal_turn(player)
        if self.winner is None:
            self.current = player.other()
        self.turns += 1

    def _normal_turn(self, player: Player) -> None:
        doubles = 0
        while True:
            d1, d2 = self._dice()
            if d1 == d2:
                doubles += 1
                if doubles == 3:
                    self._go_to_jail(player)
                    return
            self._advance(player, d1 + d2)
            if self.winner is not None or self.jail_rest[player] is not None or d1 != d2:
                return

    def _jail_turn(self, player: Player) -> None:
        if self.jail_cards[player]:
            deck_name = self.jail_cards[player].pop()
            self.decks[deck_name].release(_get_out_card(deck_name))
            self.jail_rest[player] = None
            self.position[player] = JAIL_POSITION
            self._note(f"{player.value} が釈放カードで出た")
            self._normal_turn(player)
            return
        d1, d2 = self._dice()
        if d1 == d2:  # 実機で確認: 支払いなしで出て、出た目だけ進む(続けて振らない)
            self.jail_rest[player] = None
            self._advance(player, d1 + d2)
            return
        rest = (self.jail_rest[player] or 0) + 1
        self.jail_rest[player] = rest
        if rest >= MAX_JAIL_REST:  # 実機で確認: 保釈金を払って出て、その手番の出目で進む
            self._pay(player, None, JAIL_FINE)
            if self.winner is None:
                self.jail_rest[player] = None
                self._advance(player, d1 + d2)

    def _go_to_jail(self, player: Player) -> None:
        self.position[player] = JAIL_POSITION
        self.jail_rest[player] = 0
        self._note(f"{player.value} が刑務所へ")

    def _advance(self, player: Player, steps: int) -> None:
        target = self.position[player] + steps
        if target >= BOARD_SIZE:
            self.state = rules.pass_go(self.state, player)
        self.position[player] = target % BOARD_SIZE
        self._resolve(player, steps, 0, 1, False)

    def _advance_to(
        self, player: Player, target: int, depth: int, railroad_multiplier: int, utility_ten: bool
    ) -> None:
        """前へ進んで target に止まる。GO を通る(target が現在位置以前)なら給料を受け取る。"""
        if target <= self.position[player]:
            self.state = rules.pass_go(self.state, player)
        self.position[player] = target
        dice_total = sum(self._dice()) if utility_ten else 0
        self._resolve(player, dice_total, depth, railroad_multiplier, utility_ten)

    # --- 止まったマスの処理 ---

    def _resolve(
        self,
        player: Player,
        dice_total: int,
        depth: int,
        railroad_multiplier: int,
        utility_ten: bool,
    ) -> None:
        square = BOARD[self.position[player]]
        if square.kind is SquareKind.DEED:
            self._land_on_deed(player, square.name, dice_total, railroad_multiplier, utility_ten)
        elif square.kind is SquareKind.TAX:
            self._pay(player, None, square.amount)
        elif square.kind is SquareKind.GO_TO_JAIL:
            self._go_to_jail(player)
        elif (
            square.kind in (SquareKind.CHANCE, SquareKind.COMMUNITY_CHEST)
            and depth < MAX_CARD_DEPTH
        ):
            deck_name = "chance" if square.kind is SquareKind.CHANCE else "chest"
            self._apply_card(player, deck_name, self.decks[deck_name].draw(), depth)

    def _land_on_deed(
        self,
        player: Player,
        name: str,
        dice_total: int,
        railroad_multiplier: int,
        utility_ten: bool,
    ) -> None:
        deed = self.catalogue[name]
        holding = self.state.holdings.get(name)
        if holding is None:
            policy = self.policies[player]
            if self.cash(player) >= deed.price and policy.wants_to_buy(self, player, deed):
                self.state = rules.buy(self.state, self.catalogue, player, name)
                self._note(f"{player.value} が {name} を {deed.price} で購入")
            else:
                self._auction(name, player)
            return
        if holding.owner is player or holding.mortgaged:
            return
        if deed.kind is DeedKind.UTILITY and utility_ten:
            amount = dice_total * 10
        else:
            amount = rules.rent_due(self.state, self.catalogue, name, dice_total or 7)
            if deed.kind is DeedKind.RAILROAD:
                amount *= railroad_multiplier
        self._note(f"{player.value} が {name} で {amount} を {holding.owner.value} へ支払い")
        self._pay(player, holding.owner, amount)

    def _auction(self, name: str, starter: Player) -> None:
        """見送り(買えない場合を含む)のオークション。落札額は、負けた側の上限 + 1(自分の上限まで)。"""
        deed = self.catalogue[name]
        limits = {
            p: max(0, min(self.policies[p].auction_limit(self, p, deed), self.cash(p)))
            for p in Player
        }
        high, low = max(limits.values()), min(limits.values())
        if high < 1:
            return  # 誰も入札しない
        leaders = [p for p in Player if limits[p] == high]
        winner = leaders[0] if len(leaders) == 1 else self.rng.choice(leaders)
        price = high if len(leaders) > 1 else min(high, low + 1)
        self.state = rules.acquire(self.state, winner, name, price)
        self._note(f"オークション: {winner.value} が {name} を {price} で落札")

    # --- カード ---

    def _apply_card(self, player: Player, deck_name: str, card: Card, depth: int) -> None:
        self._note(f"{player.value} が {deck_name} のカード: {card.text}")
        other = player.other()
        position = self.position[player]
        match card.kind:
            case CardKind.MOVE_TO:
                self._advance_to(player, card.target, depth + 1, 1, False)
            case CardKind.NEAREST_RAILROAD:
                self._advance_to(player, next_position(position, RAILROADS), depth + 1, 2, False)
            case CardKind.NEAREST_UTILITY:
                self._advance_to(player, next_position(position, UTILITIES), depth + 1, 1, True)
            case CardKind.BACK:
                self.position[player] = (position - card.amount) % BOARD_SIZE
                self._resolve(player, 0, depth + 1, 1, False)
            case CardKind.GET_OUT_OF_JAIL:
                self.jail_cards[player].append(deck_name)
            case CardKind.GO_TO_JAIL:
                self._go_to_jail(player)
            case CardKind.RECEIVE:
                self.state = rules.receive_from_bank(self.state, player, card.amount)
            case CardKind.PAY:
                self._pay(player, None, card.amount)
            case CardKind.PAY_EACH:
                self._pay(player, other, card.amount)
            case CardKind.COLLECT_EACH:
                self._pay(other, player, card.amount)
            case CardKind.REPAIRS:
                houses = sum(
                    h.houses
                    for h in self.state.holdings.values()
                    if h.owner is player and h.houses < HOTEL_LEVEL
                )
                hotels = sum(
                    1
                    for h in self.state.holdings.values()
                    if h.owner is player and h.houses == HOTEL_LEVEL
                )
                self._pay(player, None, houses * card.per_house + hotels * card.per_hotel)

    # --- 支払いと破産 ---

    def _pay(self, payer: Player, creditor: Player | None, amount: int) -> None:
        if amount <= 0:
            return
        self.state = rules.pay_bank(self.state, payer, amount)
        if creditor is not None:
            self.state = rules.receive_from_bank(self.state, creditor, amount)
        while self.state.cash[payer] < 0:
            if not self._liquidate_one(payer):
                self.winner = payer.other()
                self._note(f"{payer.value} が破産")
                return

    def _in_monopoly(self, player: Player, name: str) -> bool:
        deed = self.catalogue[name]
        return deed.kind is DeedKind.STREET and rules.owns_full_group(
            self.state, self.catalogue, player, deed
        )

    def _liquidate_one(self, player: Player) -> bool:
        """不足を作るため、1 つだけ換金する。できなければ False。

        順序: ① 独占でない土地を抵当に ② 家を売る(安い土地から) ③ 残りの土地を抵当に。
        """
        mine = {n: h for n, h in self.state.holdings.items() if h.owner is player}

        def cheapest(names: list[str]) -> str:
            return min(names, key=lambda n: self.catalogue[n].price)

        free = [
            n
            for n, h in mine.items()
            if not h.mortgaged and h.houses == 0 and not self._in_monopoly(player, n)
        ]
        if free:
            name = cheapest(free)
            self.state = rules.mortgage(self.state, self.catalogue, player, name)
            return True
        sellable = [n for n in mine if rules.can_sell_house(self.state, self.catalogue, player, n)]
        if sellable:
            name = cheapest(sellable)
            self.state = rules.sell_house(self.state, self.catalogue, player, name)
            return True
        rest = [n for n, h in mine.items() if not h.mortgaged and h.houses == 0]
        if rest:
            self.state = rules.mortgage(self.state, self.catalogue, player, cheapest(rest))
            return True
        return False


def _get_out_card(deck_name: str) -> Card:
    cards = CHANCE_CARDS if deck_name == "chance" else COMMUNITY_CHEST_CARDS
    return next(c for c in cards if c.kind is CardKind.GET_OUT_OF_JAIL)


__all__ = ["START_CASH", "Game", "Holding", "Policy"]
