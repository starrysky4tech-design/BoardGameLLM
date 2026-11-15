"""Monopoly の方針(購入、入札、建設、抵当の解除)。

- ExpectedValuePolicy: 第 1 段。止まる頻度と賃料から期待値を出して決める
- GreedyPolicy: 比べるための基準。買えるものは全部買い、建てられるものは全部建てる
"""

from collections.abc import Mapping
from functools import cache

from bglm.plugins.monopoly.logic import rules
from bglm.plugins.monopoly.logic.board import (
    BOARD,
    BOARD_SIZE,
    DEED_POSITION_OF,
    POSITION_OF,
    SquareKind,
)
from bglm.plugins.monopoly.logic.catalogue import STREET_GROUPS, street_groups
from bglm.plugins.monopoly.logic.engine import Game
from bglm.plugins.monopoly.logic.landing_odds import LandingOdds, next_turn_landing
from bglm.plugins.monopoly.logic.landing_table import LANDING_FREQUENCY
from bglm.plugins.monopoly.logic.models import (
    HOTEL_LEVEL,
    Deed,
    DeedKind,
    MonopolyState,
    Player,
    Trade,
)
from bglm.plugins.monopoly.logic.opponent_model import BidModel

# 次の 1 手の出目(2〜12)の確率。ゾロ目でも、まず 1 回目の移動先を考える
_DICE_WAYS = {s: 6 - abs(s - 7) for s in range(2, 13)}
_MIN_RISK_PROBABILITY = 5 / 36  # これ未満の確率の出目(2 と 12)は、最悪の額の計算から外す


@cache
def group_return_factor() -> dict[str, float]:
    """色グループごとの、「家 3 軒での稼ぎ ÷ 投資額」を、全体の平均で割った値。

    止まる頻度と賃料から出す(オレンジが最も高く、茶が最も低い)。
    """
    position_of = DEED_POSITION_OF
    ratio = {}
    for group, deeds in STREET_GROUPS.items():
        income = sum(LANDING_FREQUENCY[position_of[d.name]] * d.rent[3] for d in deeds)
        cost = sum(d.price + 3 * d.house_cost for d in deeds)
        ratio[group] = income / cost
    mean = sum(ratio.values()) / len(ratio)
    return {group: value / mean for group, value in ratio.items()}


BUILD_FUND_CAP = (
    150  # 建設の予備の上限(1 軒ぶん。暫定。300 では ₼373 でも ₼100 の土地を見送った 2026-11-10)
)
# 建設: 1 手番あたりの期待収益(相手が次の手番で止まる確率 × 賃料の増分)÷ 建設費、の下限。
# 模擬対戦(500 局ずつ)で、0.01・0.03・0.05 を比べ、低いほど強い傾向(強欲に対する勝率 51.0%・49.8%・49.4%)。
# 旧ルール(入口の手前 7 マス)との直接対戦(1200 局)は 50.2%(差は誤差の範囲)。
# 根拠と数値: .steering/20261110-monopoly-speedup-strategy/RESULT.md
BUILD_MIN_RETURN = 0.01
BUILD_SURPLUS = 600  # (仮)建てた後も、残す現金にこの額を足した現金が残るなら、下限を BUILD_SURPLUS_RETURN に下げる
BUILD_SURPLUS_RETURN = 0.005  # (仮。未調整。BUILD_MIN_RETURN 以下)
# 競り: 相手の上限の推定が、定価のこの割合(1 - 値)以下のとき、見送って競りへ回す(定価より安く取れる見込み)
AUCTION_MIN_DISCOUNT = 0.25  # (仮。実機の観測が貯まったら見直す)
RAIL_BLOCK_HORIZON = 40  # 鉄道を取られたときの賃料の増加を、残りの手番(この回数)で見積もる(暫定)
RAIL_BLOCK_STRATEGIC = (
    0.3  # 阻止の価値が定価のこの割合以上なら、戦略的な取得(定価を超えて入札してよい)
)


# 鉄道・会社の価値(定価に対する割合)。同種を持つ数が 1 つ増えるごとに STEP ずつ上がる
TRANSPORT_START = {DeedKind.RAILROAD: 0.85, DeedKind.UTILITY: 0.8}
TRANSPORT_STEP = 0.2


def transport_value(deed: Deed, owned_before: int) -> float:
    """鉄道・会社の価値(現金換算)。owned_before は、この土地を除いた、同種の所有数。"""
    return deed.price * (TRANSPORT_START[deed.kind] + TRANSPORT_STEP * owned_before)


def railroad_block_value(game: Game, player: Player, deed: Deed) -> float:
    """相手がこの鉄道を取ると、自分が止まるたびに払う賃料が増える。その増加を、阻止する価値(現金換算)。

    1 手番あたりの、自分が相手の鉄道で払う賃料の期待値(止まる頻度 × 賃料)が、取られた前後でどれだけ増えるか
    × 見積もりの手番数。相手の持つ数が多いほど大きい(3 つ持つ相手に 4 つ目を渡すと、賃料が ₼100 から ₼200)。
    2026-11-08: 4 つ目の B&O Railroad を Thimble に取られ、賃料が倍になる状況で、方針が見ていなかった。
    """
    position_of = POSITION_OF
    opponent = player.other()
    owned = [
        n
        for n, h in game.state.holdings.items()
        if h.owner is opponent and game.catalogue[n].kind is DeedKind.RAILROAD
    ]
    before = len(owned)
    if before >= len(deed.rent):  # すでに最大
        return 0.0
    rent = deed.rent
    old = sum(LANDING_FREQUENCY[position_of[n]] for n in owned) * (
        rent[before - 1] if before else 0
    )
    new = (
        sum(LANDING_FREQUENCY[position_of[n]] for n in owned)
        + LANDING_FREQUENCY[position_of[deed.name]]
    ) * rent[before]
    return max(0.0, (new - old) * RAIL_BLOCK_HORIZON)


class GreedyPolicy:
    """基準の方針。買えるものは買い、入札は価格まで、建てられるものは(現金 100 を残して)全部建てる。

    取引は持ちかけない。受けるのは、受け取る価格(土地の定価 + 現金)が、渡す価格以上のときだけ
    (独占の価値は見ない、単純な基準)。
    """

    def propose_trades(self, game: Game, player: Player) -> list[Trade]:
        return []

    def respond_to_trade(self, game: Game, player: Player, proposer: Player, trade: Trade) -> bool:
        price = {name: game.catalogue[name].price for name in game.catalogue}
        received = sum(price[n] for n in trade.proposer_deeds) + trade.proposer_cash
        given = sum(price[n] for n in trade.partner_deeds) + trade.partner_cash
        return received >= given

    def wants_to_buy(self, game: Game, player: Player, deed: Deed) -> bool:
        return game.cash(player) >= deed.price

    def auction_limit(self, game: Game, player: Player, deed: Deed) -> int:
        return min(deed.price, game.cash(player))

    def manage(self, game: Game, player: Player) -> None:
        progress = True
        while progress:
            progress = False
            for name, holding in list(game.state.holdings.items()):
                if holding.owner is not player or not game.can_build(player, name):
                    continue
                if game.cash(player) - game.catalogue[name].house_cost >= 100:
                    game.build(player, name)
                    progress = True


class ExpectedValuePolicy:
    """第 1 段の方針: 期待値で買い、入札し、建て、抵当を解除する。"""

    def __init__(
        self,
        reserve_min: int = 60,
        complete_bonus: float = 1.0,
        block_bonus: float = 0.9,
        owned_bonus: float = 0.35,
        blocked_discount: float = 0.85,
        trade: bool = True,
        trade_margin: int = 20,
        auction_when_opponent_poor: bool = True,
        deny_bonus: float = 0.6,
        first_deny_bonus: float = 0.25,
        build_min_return: float = BUILD_MIN_RETURN,
        build_surplus: int = BUILD_SURPLUS,
        build_surplus_return: float = BUILD_SURPLUS_RETURN,
    ) -> None:
        if not 0 < build_min_return <= 1:
            raise ValueError(f"build_min_return は 0 より大きく 1 以下: {build_min_return}")
        if not 0 <= build_surplus_return <= build_min_return:
            raise ValueError(
                f"build_surplus_return は 0 以上 build_min_return 以下: {build_surplus_return}"
            )
        if build_surplus < 0:
            raise ValueError(f"build_surplus は 0 以上: {build_surplus}")
        self.bid_model: BidModel | None = (
            None  # 相手の入札の上限の推定(`Decider` が持つものを共有する)
        )
        self.build_min_return = build_min_return
        self.build_surplus = build_surplus
        self.build_surplus_return = build_surplus_return
        # 妨害価値(相手の独占を分断する価値、定価に対する割合)。2026-11-08 の敗因: ピンクを見送り、揃えさせた
        self.deny_bonus = (
            deny_bonus  # 相手が同色を持ち、自分が 0 枚のとき。相手の持ち分(割合)に比例
        )
        self.first_deny_bonus = first_deny_bonus  # 誰も持たない色の最初の 1 枚
        self.reserve_min = reserve_min  # 最低限残す現金
        self.complete_bonus = complete_bonus  # 独占が完成する土地に足す価値(価格に対する割合)
        self.block_bonus = block_bonus  # 相手の独占を阻止する土地に足す価値
        self.owned_bonus = owned_bonus  # 同色の土地を持つほど、1 軒ごとに足す価値の割合
        self.blocked_discount = blocked_discount  # 相手が同色を持っていて、独占できないときの割引
        self.trade = trade  # False なら、取引を持ちかけず、受けもしない
        self.trade_margin = trade_margin  # 取引で、資産の差がこれ以上増えるときだけ受ける
        # True なら、相手が定価を払えないとき、買わずにオークションへ回す(落札額は相手の現金程度に下がる)
        self.auction_when_opponent_poor = auction_when_opponent_poor

    # --- 価値と、残すべき現金 ---

    def deed_value(self, game: Game, player: Player, deed: Deed) -> tuple[float, bool]:
        """この土地を手に入れる価値(現金換算)と、独占に関わる(完成・阻止)か。"""
        if deed.kind is DeedKind.RAILROAD:
            owned = rules.owned_of_kind(game.state, game.catalogue, player, DeedKind.RAILROAD)
            block = railroad_block_value(game, player, deed)  # 相手に取られると、賃料が上がる分
            return transport_value(deed, owned) + block, block >= RAIL_BLOCK_STRATEGIC * deed.price
        if deed.kind is DeedKind.UTILITY:
            owned = rules.owned_of_kind(game.state, game.catalogue, player, DeedKind.UTILITY)
            return transport_value(deed, owned), False
        others = deed.group_size - 1
        mine, theirs = rules.group_counts(game.state, game.catalogue, player, deed)
        base = deed.price * group_return_factor()[deed.group]
        if mine == others:  # 手に入れると、独占が完成する
            return base + deed.price * self.complete_bonus, True
        if theirs == others:  # 相手が残りを全部持っている。取ると、相手の独占を阻止できる
            return base + deed.price * self.block_bonus, True
        if theirs > 0 and mine > 0:  # 相手が持っていて、自分は独占できない
            return base * self.blocked_discount, False
        if theirs > 0:  # 自分は 0 枚。取ると、相手が揃える道を 1 枚ぶん塞ぐ(妨害価値)
            deny = deed.price * self.deny_bonus * theirs / others
            return base + deny, deny >= RAIL_BLOCK_STRATEGIC * deed.price
        # 誰も持っていない、または自分だけが持つ。自分が 0 枚なら、最初の 1 枚から妨害価値を入れる
        deny = deed.price * self.first_deny_bonus if mine == 0 else 0.0
        return base * (1 + self.owned_bonus * mine) + deny, False

    def worst_next_payment(self, game: Game, player: Player) -> int:
        """次の 1 手で払う可能性のある、最悪の額(相手の所有地の賃料と税金)。"""
        opponent = player.other()
        position = game.position[player]
        worst = 0
        for dice, ways in _DICE_WAYS.items():
            if ways / 36 < _MIN_RISK_PROBABILITY:
                continue
            square = BOARD[(position + dice) % BOARD_SIZE]
            pay = 0
            if square.kind is SquareKind.DEED:
                holding = game.state.holdings.get(square.name)
                if holding is not None and holding.owner is opponent:
                    pay = rules.rent_due(game.state, game.catalogue, square.name, dice)
            elif square.kind is SquareKind.TAX:
                pay = square.amount
            worst = max(worst, pay)
        return worst

    def reserve(self, game: Game, player: Player) -> int:
        return max(self.reserve_min, self.worst_next_payment(game, player))

    def build_fund(self, game: Game, player: Player) -> int:
        """揃えた色に家を建てるための予備。建てられる土地ごとに 1 軒ぶん、上限 BUILD_FUND_CAP。"""
        cost = sum(
            game.catalogue[n].house_cost
            for n, h in game.state.holdings.items()
            if h.owner is player and game.can_build(player, n)
        )
        return min(cost, BUILD_FUND_CAP)

    # --- 方針の入口 ---

    def wants_to_buy(self, game: Game, player: Player, deed: Deed) -> bool:
        value, strategic = self.deed_value(game, player, deed)
        if value < deed.price:
            return False
        # 相手が定価を払えないなら、見送って競り落とす。落札額は相手の現金 + 1 までに下がる
        if self.auction_when_opponent_poor and game.cash(player.other()) < deed.price:
            return False
        # 相手の入札の上限が定価より十分低いと推定でき、その額で落札できるなら、見送って競りへ回す
        if self._cheaper_by_auction(game, player, deed, strategic):
            return False
        return game.cash(player) - deed.price >= self._keep(game, player, strategic)

    def _cheaper_by_auction(self, game: Game, player: Player, deed: Deed, strategic: bool) -> bool:
        """競りに回すと、定価より安く取れる見込みが高いか。独占に関わる土地・妨害価値のある土地は、回さない。"""
        model = self.bid_model
        if model is None or model.conservative or strategic:
            return False
        if (
            deed.kind is DeedKind.STREET
            and rules.group_counts(game.state, game.catalogue, player, deed)[1] > 0
        ):
            return False  # 相手が同色を持つ。相手に取られると、独占に近づく
        ceiling = model.ceiling(deed.price, game.cash(player.other()))
        if ceiling + 1 > deed.price * (1 - AUCTION_MIN_DISCOUNT):
            return False
        return self.auction_limit(game, player, deed) >= ceiling + 1  # その額で、自分が落札できる

    def auction_keep(self, game: Game, player: Player, deed: Deed) -> int:
        """競りで、落札した後に残す現金。"""
        _value, strategic = self.deed_value(game, player, deed)
        return self._keep(game, player, strategic)

    def _keep(self, game: Game, player: Player, strategic: bool) -> int:
        """土地を手に入れた後に残す現金。独占に関わる(戦略的な)土地は最低限、それ以外は予備と建設費を残す。"""
        if strategic:
            return self.reserve_min
        return self.reserve(game, player) + self.build_fund(game, player)

    def auction_limit(self, game: Game, player: Player, deed: Deed) -> int:
        value, strategic = self.deed_value(game, player, deed)
        keep = self.auction_keep(game, player, deed)
        # 上限は標準価格(定価)まで。ただし、取ると自分の独占が完成するなら、価値の範囲で定価を超えて入札する。
        # 上限を超える額が必要になったら、入札をやめる(降りる)
        cap = (
            int(value)
            if strategic or self._completes_group(game, player, deed)
            else min(int(value), deed.price)
        )
        return max(0, min(cap, game.cash(player) - keep))

    def _completes_group(self, game: Game, player: Player, deed: Deed) -> bool:
        """この土地を取ると、自分が同じ色のグループを全部持つ(独占が完成する)。"""
        if deed.kind is not DeedKind.STREET:
            return False
        mine, _theirs = rules.group_counts(game.state, game.catalogue, player, deed)
        return mine == deed.group_size - 1

    def manage(self, game: Game, player: Player) -> None:
        self._unmortgage(game, player)
        self._build(game, player)

    def _unmortgage(self, game: Game, player: Player) -> None:
        keep = self.reserve(game, player) + 100
        names = [n for n, h in game.state.holdings.items() if h.owner is player and h.mortgaged]
        names.sort(key=lambda n: -game.catalogue[n].price)
        for name in names:
            cost = rules.unmortgage_cost(game.catalogue[name])
            if game.cash(player) - cost >= keep:
                game.unmortgage(player, name)

    def _build(self, game: Game, player: Player) -> None:
        opponent = player.other()
        rest = game.jail_rest[opponent]
        odds = next_turn_landing(
            game.position[opponent], in_jail=rest is not None, jail_failed=min(rest or 0, 2)
        )
        keep = self.reserve(game, player) + 50
        while True:
            plan = self._best_build(game, player, odds, keep)
            if plan is None:
                return
            for name in plan:
                game.build(player, name)

    @staticmethod
    def _rent_at(deed: Deed, level: int) -> int:
        """独占の街の賃料。家 0 軒は、基本賃料の 2 倍(独占の賃料)。"""
        return 2 * deed.rent[0] if level == 0 else deed.rent[level]

    def _best_build(
        self, game: Game, player: Player, odds: LandingOdds, keep: int
    ) -> list[str] | None:
        """いま建てる、期待収益の最も高い建設の束(土地の名前を、建てる順に)。無ければ None。

        均等に建てる規則があるので、ある土地に次の 1 軒を建てるには、同色の他の土地を先に同じ段まで建てる必要がある。
        その分の費用と収益も含めた「束」で比べる(止まる確率の低い土地を先に建てないと、確率の高い土地が建てられない)。
        収益 = Σ(相手が次の手番でその土地に止まる確率 × 賃料の増分)。ホテルも同じ式。
        """
        position_of = DEED_POSITION_OF
        holdings = game.state.holdings
        best: tuple[float, float, list[str]] | None = None
        for members in street_groups(game.catalogue).values():
            held = [holdings.get(d.name) for d in members]
            if any(h is None or h.owner is not player or h.mortgaged for h in held):
                continue
            levels = {d.name: holdings[d.name].houses for d in members}
            deeds = {d.name: d for d in members}
            for target in members:
                if levels[target.name] >= HOTEL_LEVEL:
                    continue
                goal = levels[target.name] + 1
                trial = dict(levels)
                plan: list[str] = []
                while True:  # 他の土地を、goal - 1 の段まで、低い順に建てる
                    lows = [n for n in trial if n != target.name and trial[n] < goal - 1]
                    if not lows:
                        break
                    n = min(lows, key=lambda x: (trial[x], x))
                    plan.append(n)
                    trial[n] += 1
                plan.append(target.name)
                trial[target.name] += 1
                cost = sum(deeds[n].house_cost for n in plan)
                after = game.cash(player) - cost
                if after < keep:
                    continue
                step = dict(levels)
                gain = 0.0
                for n in plan:
                    deed = deeds[n]
                    gain += odds.at(position_of[n]) * (
                        self._rent_at(deed, step[n] + 1) - self._rent_at(deed, step[n])
                    )
                    step[n] += 1
                if gain <= 0:
                    continue
                threshold = (
                    self.build_surplus_return
                    if after >= keep + self.build_surplus
                    else self.build_min_return
                )
                ratio = gain / cost
                if ratio < threshold:
                    continue
                if best is None or (ratio, gain) > (best[0], best[1]):
                    best = (ratio, gain, plan)
        return best[2] if best else None

    # --- 取引 ---

    def portfolio_value(
        self, state: MonopolyState, catalogue: Mapping[str, Deed], player: Player
    ) -> float:
        """現金換算の資産。土地の価値は、同色の持ち方(独占、相手が持っている)で変わる。"""
        total = float(state.cash[player])
        factor = group_return_factor()
        for name, holding in state.holdings.items():
            if holding.owner is not player:
                continue
            deed = catalogue[name]
            if holding.mortgaged:
                total += deed.mortgage
                continue
            total += holding.houses * deed.house_cost
            if deed.kind is DeedKind.RAILROAD or deed.kind is DeedKind.UTILITY:
                owned = rules.owned_of_kind(state, catalogue, player, deed.kind)
                total += transport_value(deed, owned - 1)
                continue
            mine, theirs = rules.group_counts(state, catalogue, player, deed)
            base = deed.price * factor[deed.group]
            if mine == deed.group_size:
                total += base + deed.price * self.complete_bonus
            elif theirs > 0:
                total += base * self.blocked_discount
            else:
                total += base * (1 + self.owned_bonus * (mine - 1))
        return total

    def margin_gain(
        self,
        state: MonopolyState,
        state_after: MonopolyState,
        catalogue: Mapping[str, Deed],
        player: Player,
    ) -> float:
        """取引で、(自分の資産 − 相手の資産)がどれだけ増えるか。2 人対局なので、相手の得は自分の損。"""
        opponent = player.other()

        def gap(s: MonopolyState) -> float:
            return self.portfolio_value(s, catalogue, player) - self.portfolio_value(
                s, catalogue, opponent
            )

        return gap(state_after) - gap(state)

    def respond_to_trade(self, game: Game, player: Player, proposer: Player, trade: Trade) -> bool:
        if not self.trade:
            return False
        try:
            after = rules.apply_trade(game.state, game.catalogue, proposer, player, trade)
        except ValueError:
            return False
        return self.margin_gain(game.state, after, game.catalogue, player) > self.trade_margin

    def propose_trades(self, game: Game, player: Player) -> list[Trade]:
        """独占を完成させる土地を、現金で買い取る提案。安い額から順に並べる。

        対象: 同色の残り 1 軒を相手が持っていて、取ると自分の独占が完成する土地。
        """
        if not self.trade:
            return []
        opponent = player.other()
        offers: list[tuple[int, Trade]] = []
        for name, holding in game.state.holdings.items():
            if holding.owner is not opponent or holding.houses:
                continue
            deed = game.catalogue[name]
            if deed.kind is not DeedKind.STREET:
                continue
            mine, _theirs = rules.group_counts(game.state, game.catalogue, player, deed)
            if mine != deed.group_size - 1:
                continue
            for multiplier in (1.0, 1.3, 1.7, 2.2, 3.0):
                cash = int(deed.price * multiplier) // 10 * 10
                if cash > game.cash(player) - self.reserve_min:
                    break
                offer = Trade(partner_deeds=frozenset({name}), proposer_cash=cash)
                if not rules.can_trade(game.state, game.catalogue, player, opponent, offer):
                    continue
                after = rules.apply_trade(game.state, game.catalogue, player, opponent, offer)
                if self.margin_gain(game.state, after, game.catalogue, player) > self.trade_margin:
                    offers.append((cash, offer))
        return [offer for _cash, offer in sorted(offers, key=lambda pair: pair[0])]
