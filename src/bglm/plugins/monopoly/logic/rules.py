"""Monopoly のルール: 賃料、購入、抵当、GO の受け取り、支払い(仕様は LOGIC_SPEC.md の 2〜5)。

カードの文面の解釈と、手番の進行は含まない。残高が負になることは許す(実機では、負になると
抵当や売却を求められる。その処理は呼び出し側が行う)。
"""

from collections.abc import Mapping
from dataclasses import replace

from bglm.plugins.monopoly.logic.models import (
    GO_SALARY,
    HOTEL_LEVEL,
    Deed,
    DeedKind,
    Holding,
    MonopolyState,
    Player,
    Trade,
)

UTILITY_MULTIPLIERS = (4, 10)  # 会社 1 つ、2 つ(サイコロの目に掛ける)


def _check_dice(total: int) -> None:
    if not 2 <= total <= 12:
        raise ValueError(f"サイコロの合計は 2〜12: {total}")


def _with_cash(state: MonopolyState, player: Player, delta: int) -> MonopolyState:
    cash = dict(state.cash)
    cash[player] = cash[player] + delta
    return replace(state, cash=cash)


def _with_holding(state: MonopolyState, name: str, holding: Holding) -> MonopolyState:
    holdings = dict(state.holdings)
    holdings[name] = holding
    return replace(state, holdings=holdings)


def owned_of_kind(
    state: MonopolyState, catalogue: Mapping[str, Deed], owner: Player, kind: DeedKind
) -> int:
    """そのプレイヤーが所有する、指定の種類の土地の数(抵当中も数える)。"""
    return sum(
        1
        for name, holding in state.holdings.items()
        if holding.owner is owner and catalogue[name].kind is kind
    )


def group_counts(
    state: MonopolyState, catalogue: Mapping[str, Deed], player: Player, deed: Deed
) -> tuple[int, int]:
    """同色の街(土地のみ)のうち、(player が持つ数, 相手が持つ数)。抵当中も数える。"""
    mine = theirs = 0
    for name, holding in state.holdings.items():
        other = catalogue[name]
        if other.group != deed.group or other.kind is not DeedKind.STREET:
            continue
        if holding.owner is player:
            mine += 1
        else:
            theirs += 1
    return mine, theirs


def owns_full_group(
    state: MonopolyState, catalogue: Mapping[str, Deed], owner: Player, deed: Deed
) -> bool:
    """同色グループの土地を全部持っているか(土地 STREET のみ)。"""
    return group_counts(state, catalogue, owner, deed)[0] == deed.group_size


def rent_due(
    state: MonopolyState, catalogue: Mapping[str, Deed], name: str, dice_total: int
) -> int:
    """そのマスに止まった人が、所有者へ払う額。所有なし、抵当中は 0。"""
    deed = catalogue[name]
    holding = state.holdings.get(name)
    if holding is None or holding.mortgaged:
        return 0
    if deed.kind is DeedKind.STREET:
        if holding.houses:
            return deed.rent[holding.houses]  # 家 1〜4、ホテル(5)
        base = deed.rent[0]
        return base * 2 if owns_full_group(state, catalogue, holding.owner, deed) else base
    if deed.kind is DeedKind.RAILROAD:
        count = owned_of_kind(state, catalogue, holding.owner, DeedKind.RAILROAD)
        return deed.rent[count - 1]
    _check_dice(dice_total)
    count = owned_of_kind(state, catalogue, holding.owner, DeedKind.UTILITY)
    return dice_total * UTILITY_MULTIPLIERS[min(count, 2) - 1]


def land(
    state: MonopolyState,
    catalogue: Mapping[str, Deed],
    player: Player,
    name: str,
    dice_total: int,
) -> tuple[MonopolyState, int]:
    """止まったマスの支払いを行う。払った額を返す。購入はしない(Buy は別の操作)。"""
    holding = state.holdings.get(name)
    if holding is None or holding.owner is player:
        return state, 0
    amount = rent_due(state, catalogue, name, dice_total)
    if amount == 0:
        return state, 0
    state = _with_cash(state, player, -amount)
    state = _with_cash(state, holding.owner, amount)
    return state, amount


def acquire(state: MonopolyState, player: Player, name: str, price: int) -> MonopolyState:
    """未所有の土地を、指定の額で手に入れる(購入、オークションの落札)。足りなければ ValueError。"""
    if name in state.holdings:
        raise ValueError(f"{name} はすでに所有されている")
    if state.cash[player] < price:
        raise ValueError(f"{name} の価格 {price} に対して所持金が足りない")
    state = _with_cash(state, player, -price)
    return _with_holding(state, name, Holding(owner=player))


def buy(
    state: MonopolyState, catalogue: Mapping[str, Deed], player: Player, name: str
) -> MonopolyState:
    """未所有の土地を、定価で銀行から買う。所持金が足りなければ ValueError。"""
    return acquire(state, player, name, catalogue[name].price)


def mortgage(
    state: MonopolyState, catalogue: Mapping[str, Deed], player: Player, name: str
) -> MonopolyState:
    """所有する土地を抵当に入れ、抵当価値を受け取る。家が建っていれば ValueError。"""
    holding = state.holdings.get(name)
    if holding is None or holding.owner is not player:
        raise ValueError(f"{name} は {player.value} の所有ではない")
    if holding.mortgaged:
        raise ValueError(f"{name} はすでに抵当に入っている")
    if holding.houses:
        raise ValueError(f"{name} に家が建っているため抵当に入れられない")
    state = _with_cash(state, player, catalogue[name].mortgage)
    return _with_holding(state, name, replace(holding, mortgaged=True))


def pass_go(state: MonopolyState, player: Player) -> MonopolyState:
    """GO を通過して、給料を受け取る。"""
    return _with_cash(state, player, GO_SALARY)


def pay_bank(state: MonopolyState, player: Player, amount: int) -> MonopolyState:
    """銀行へ払う(税金、カードの支払いなど)。残高は負になることがある。"""
    return _with_cash(state, player, -amount)


def receive_from_bank(state: MonopolyState, player: Player, amount: int) -> MonopolyState:
    """銀行から受け取る(カードの受け取りなど)。"""
    return _with_cash(state, player, amount)


def is_insolvent(state: MonopolyState, player: Player) -> bool:
    """残高が負か。負になると、抵当や売却で不足を作る必要がある。"""
    return state.cash[player] < 0


# --- 建設・売却・抵当の解除 ---


def group_members(catalogue: Mapping[str, Deed], deed: Deed) -> list[Deed]:
    return [d for d in catalogue.values() if d.group == deed.group]


def _house_levels(
    state: MonopolyState, catalogue: Mapping[str, Deed], deed: Deed
) -> dict[str, Holding]:
    return {d.name: state.holdings[d.name] for d in group_members(catalogue, deed)}


def _check_build(
    state: MonopolyState, catalogue: Mapping[str, Deed], player: Player, name: str
) -> Deed:
    deed = catalogue[name]
    holding = state.holdings.get(name)
    if deed.kind is not DeedKind.STREET:
        raise ValueError(f"{name} は土地ではないため、家を建てられない")
    if holding is None or holding.owner is not player:
        raise ValueError(f"{name} は {player.value} の所有ではない")
    if not owns_full_group(state, catalogue, player, deed):
        raise ValueError(f"{name} は同色グループが揃っていない")
    levels = _house_levels(state, catalogue, deed)
    if any(h.mortgaged for h in levels.values()):
        raise ValueError(f"{name} のグループに抵当中の土地がある")
    if holding.houses >= HOTEL_LEVEL:
        raise ValueError(f"{name} はすでにホテルが建っている")
    if holding.houses > min(h.houses for h in levels.values()):
        raise ValueError(f"{name} は、偏りなく建てる規則に反する")
    if state.cash[player] < deed.house_cost:
        raise ValueError(f"{name} の建設費 {deed.house_cost} に対して所持金が足りない")
    return deed


def can_build(
    state: MonopolyState, catalogue: Mapping[str, Deed], player: Player, name: str
) -> bool:
    try:
        _check_build(state, catalogue, player, name)
    except ValueError:
        return False
    return True


def build(
    state: MonopolyState, catalogue: Mapping[str, Deed], player: Player, name: str
) -> MonopolyState:
    """家を 1 軒(4 軒の次はホテル)建てる。条件を満たさなければ ValueError。

    条件: 同色グループが揃っている、抵当中の土地が無い、偏りなく建てる(最も少ない土地にだけ建てられる)、
    所持金が足りる。ホテルは、グループの全部に家が 4 軒あるときだけ建てられ、家 1 軒分の費用がかかる。
    """
    deed = _check_build(state, catalogue, player, name)
    holding = state.holdings[name]
    state = _with_cash(state, player, -deed.house_cost)
    return _with_holding(state, name, replace(holding, houses=holding.houses + 1))


def can_sell_house(
    state: MonopolyState, catalogue: Mapping[str, Deed], player: Player, name: str
) -> bool:
    """売れるか。ホテルは、グループの家が 4 軒以上なら売れる(家 4 軒に戻る)。
    家は、グループで一番多い(ホテルは 4 軒とみなす)土地からだけ売れる。

    実機(2026-11-01): 家 4 軒の土地を売ると、ほかのホテルも家 4 軒に戻り、売れた。
    """
    holding = state.holdings.get(name)
    deed = catalogue[name]
    if holding is None or holding.owner is not player or holding.houses == 0:
        return False
    levels = _house_levels(state, catalogue, deed)
    if holding.houses == HOTEL_LEVEL:
        return all(h.houses >= HOTEL_LEVEL - 1 for n, h in levels.items() if n != name)
    return holding.houses == max(min(h.houses, HOTEL_LEVEL - 1) for h in levels.values())


def sell_house(
    state: MonopolyState, catalogue: Mapping[str, Deed], player: Player, name: str
) -> MonopolyState:
    """家を 1 軒売り、建設費の半額を受け取る。売るのがホテルなら、家 4 軒に戻る。

    家を売るとき、同じグループのほかのホテルは、家 4 軒に戻る(1 軒につき建設費の半額を受け取る)。
    実機の確認(2026-11-01): ホテル 1 軒の売却は ₼25。家 4 軒の土地を売ると、ほかの 2 軒のホテルも
    家 4 軒に戻り、合計 ₼75 を受け取った。
    """
    if not can_sell_house(state, catalogue, player, name):
        raise ValueError(f"{name} の家は、いまは売れない")
    holding = state.holdings[name]
    half = catalogue[name].house_cost // 2
    if holding.houses == HOTEL_LEVEL:
        state = _with_cash(state, player, half)
        return _with_holding(state, name, replace(holding, houses=HOTEL_LEVEL - 1))
    for other, other_holding in _house_levels(state, catalogue, catalogue[name]).items():
        if other != name and other_holding.houses == HOTEL_LEVEL:
            state = _with_cash(state, player, half)
            state = _with_holding(state, other, replace(other_holding, houses=HOTEL_LEVEL - 1))
    state = _with_cash(state, player, half)
    return _with_holding(state, name, replace(holding, houses=holding.houses - 1))


def unmortgage_cost(deed: Deed) -> int:
    """抵当を解除する費用。抵当価値に 1 割の利息(標準ルールの仮定。実機で未確認)。"""
    return deed.mortgage + (deed.mortgage + 9) // 10


def unmortgage(
    state: MonopolyState, catalogue: Mapping[str, Deed], player: Player, name: str
) -> MonopolyState:
    holding = state.holdings.get(name)
    if holding is None or holding.owner is not player or not holding.mortgaged:
        raise ValueError(f"{name} は {player.value} の抵当中の土地ではない")
    cost = unmortgage_cost(catalogue[name])
    if state.cash[player] < cost:
        raise ValueError(f"{name} の解除費用 {cost} に対して所持金が足りない")
    state = _with_cash(state, player, -cost)
    return _with_holding(state, name, replace(holding, mortgaged=False))


def net_worth(state: MonopolyState, catalogue: Mapping[str, Deed], player: Player) -> int:
    """現金と、所有物の価値(抵当中は抵当価値、そうでなければ価格)と、建てた家の建設費の合計。"""
    total = state.cash[player]
    for name, holding in state.holdings.items():
        if holding.owner is not player:
            continue
        deed = catalogue[name]
        total += deed.mortgage if holding.mortgaged else deed.price
        total += holding.houses * deed.house_cost
    return total


# --- 取引 ---


def mortgage_interest(deed: Deed) -> int:
    """抵当中の土地を取引で受け取るときに払う利息(抵当価値の 1 割。標準ルールの仮定。実機で未確認)。"""
    return (deed.mortgage + 9) // 10


def check_trade(
    state: MonopolyState,
    catalogue: Mapping[str, Deed],
    proposer: Player,
    partner: Player,
    trade: Trade,
) -> None:
    """取引が成立する条件を確かめる。満たさなければ ValueError。

    条件: 何かを交換する、渡す土地を実際に持っている、家が建っている色グループの土地は渡せない
    (家を売ってから)、渡す現金がある、抵当中の土地を受け取る側が利息を払える。
    """
    if trade.is_empty():
        raise ValueError("何も交換しない取引")
    sides = (
        (proposer, trade.proposer_deeds, trade.proposer_cash, trade.partner_deeds),
        (partner, trade.partner_deeds, trade.partner_cash, trade.proposer_deeds),
    )
    for giver, deeds, cash, _received in sides:
        if cash < 0 or cash > state.cash[giver]:
            raise ValueError(f"{giver.value} の渡す現金 {cash} が、所持金を超える")
        for name in deeds:
            holding = state.holdings.get(name)
            if holding is None or holding.owner is not giver:
                raise ValueError(f"{name} は {giver.value} の所有ではない")
            deed = catalogue[name]
            if deed.kind is DeedKind.STREET and any(
                state.holdings[m.name].houses > 0
                for m in group_members(catalogue, deed)
                if m.name in state.holdings
            ):
                raise ValueError(f"{name} の色グループに家が建っているため、取引できない")
    for receiver, received in (
        (partner, trade.proposer_deeds),
        (proposer, trade.partner_deeds),
    ):
        interest = sum(
            mortgage_interest(catalogue[n]) for n in received if state.holdings[n].mortgaged
        )
        cash_after = (
            state.cash[receiver]
            + (trade.proposer_cash if receiver is partner else trade.partner_cash)
            - (trade.partner_cash if receiver is partner else trade.proposer_cash)
        )
        if cash_after < interest:
            raise ValueError(f"{receiver.value} は、抵当中の土地の利息 {interest} を払えない")


def can_trade(
    state: MonopolyState,
    catalogue: Mapping[str, Deed],
    proposer: Player,
    partner: Player,
    trade: Trade,
) -> bool:
    try:
        check_trade(state, catalogue, proposer, partner, trade)
    except ValueError:
        return False
    return True


def apply_trade(
    state: MonopolyState,
    catalogue: Mapping[str, Deed],
    proposer: Player,
    partner: Player,
    trade: Trade,
) -> MonopolyState:
    """取引を実行する。土地と現金を交換し、抵当中の土地を受け取った側が利息を銀行へ払う。"""
    check_trade(state, catalogue, proposer, partner, trade)
    state = _with_cash(state, proposer, trade.partner_cash - trade.proposer_cash)
    state = _with_cash(state, partner, trade.proposer_cash - trade.partner_cash)
    for names, new_owner in ((trade.proposer_deeds, partner), (trade.partner_deeds, proposer)):
        for name in names:
            holding = state.holdings[name]
            if holding.mortgaged:
                state = _with_cash(state, new_owner, -mortgage_interest(catalogue[name]))
            state = _with_holding(state, name, replace(holding, owner=new_owner))
    return state
