"""家賃などが払えないときの、資金調達の順序(画面には依存しない)。

優先順(2026-11-08 の指示):
 1. 同色グループが揃っていない街を、安い方から抵当に入れる
 2. 鉄道・会社を、収益が低い方から抵当に入れる
 3. 1・2 で抵当に入れた土地を、抵当に入れたまま、相手と取引して現金に替える
 4. 家・ホテルが建っているグループを、土地の評価が低いグループから、家・ホテルを売る
 (4 の後も足りなければ、家の無くなった独占の土地を、評価の低い順に抵当に入れる)

`next_step` は、いまの状態から、最初に取る 1 手だけを返す。実行して状態が変わったら、もう一度呼ぶ。
取引(3)は、相手が受けない(実行できない)ことがあるので、`refused_trades` に入れて、次の手へ進む。
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from bglm.plugins.monopoly.logic import rules
from bglm.plugins.monopoly.logic.board import POSITION_OF
from bglm.plugins.monopoly.logic.landing_table import LANDING_FREQUENCY
from bglm.plugins.monopoly.logic.models import Deed, DeedKind, MonopolyState, Player, Trade
from bglm.plugins.monopoly.logic.policies import group_return_factor

_AVERAGE_DICE = 7  # 会社の賃料の目安に使う出目


class StepKind(Enum):
    MORTGAGE = "mortgage"
    TRADE_MORTGAGED = "trade_mortgaged"
    SELL_HOUSE = "sell_house"


@dataclass(frozen=True)
class FundingStep:
    kind: StepKind
    name: str  # 対象の土地(取引なら、渡す土地)
    gain: int  # 見込みの増える現金(取引は、求める現金)
    trade: Trade | None = None


def income_estimate(
    state: MonopolyState, catalogue: Mapping[str, Deed], player: Player, name: str
) -> float:
    """鉄道・会社の、1 手あたりの収益の目安。止まる頻度 × いまの所有数での賃料。"""
    deed = catalogue[name]
    owned = rules.owned_of_kind(state, catalogue, player, deed.kind)
    if deed.kind is DeedKind.RAILROAD:
        rent = deed.rent[min(owned, len(deed.rent)) - 1]
    else:
        rent = (4 if owned <= 1 else 10) * _AVERAGE_DICE
    return LANDING_FREQUENCY[POSITION_OF[name]] * rent


def _mortgageable(state: MonopolyState, player: Player) -> list[str]:
    return [
        n
        for n, h in state.holdings.items()
        if h.owner is player and not h.mortgaged and h.houses == 0
    ]


def _group_has_houses(state: MonopolyState, catalogue: Mapping[str, Deed], name: str) -> bool:
    deed = catalogue[name]
    return any(
        state.holdings[m.name].houses > 0
        for m in rules.group_members(catalogue, deed)
        if m.name in state.holdings
    )


def next_step(
    state: MonopolyState,
    catalogue: Mapping[str, Deed],
    me: Player,
    refused_trades: frozenset[str] = frozenset(),
) -> FundingStep | None:
    """資金調達で、いま取る 1 手。もう手が無ければ None。"""
    free = [n for n in _mortgageable(state, me) if not _group_has_houses(state, catalogue, n)]

    # 1. 揃っていない街を、安い方から抵当に入れる
    incomplete_streets = [
        n
        for n in free
        if catalogue[n].kind is DeedKind.STREET
        and not rules.owns_full_group(state, catalogue, me, catalogue[n])
    ]
    if incomplete_streets:
        name = min(incomplete_streets, key=lambda n: catalogue[n].price)
        return FundingStep(StepKind.MORTGAGE, name, catalogue[name].mortgage)

    # 2. 鉄道・会社を、収益が低い方から抵当に入れる
    transport = [n for n in free if catalogue[n].kind is not DeedKind.STREET]
    if transport:
        name = min(transport, key=lambda n: income_estimate(state, catalogue, me, n))
        return FundingStep(StepKind.MORTGAGE, name, catalogue[name].mortgage)

    # 3. 抵当に入れた土地を、抵当に入れたまま、相手と取引する(相手が払う利息を引いた額まで求める)
    opponent = me.other()
    for name, holding in sorted(
        state.holdings.items(), key=lambda item: catalogue[item[0]].mortgage
    ):
        if holding.owner is not me or not holding.mortgaged or name in refused_trades:
            continue
        deed = catalogue[name]
        ask = min(deed.mortgage, max(0, state.cash[opponent] - rules.mortgage_interest(deed)))
        offer = Trade(proposer_deeds=frozenset({name}), partner_cash=ask)
        if ask > 0 and rules.can_trade(state, catalogue, me, opponent, offer):
            return FundingStep(StepKind.TRADE_MORTGAGED, name, ask, offer)

    # 4. 家・ホテルを、土地の評価が低いグループから売る
    factor = group_return_factor()
    sellable = [n for n in state.holdings if rules.can_sell_house(state, catalogue, me, n)]
    if sellable:
        name = min(sellable, key=lambda n: (factor[catalogue[n].group], -POSITION_OF[n]))
        return FundingStep(StepKind.SELL_HOUSE, name, catalogue[name].house_cost // 2)

    # 5. 家の無くなった独占の土地を、評価の低い順に抵当に入れる(家のあるグループは、まだ抵当に入れられない)
    rest = [n for n in _mortgageable(state, me) if not _group_has_houses(state, catalogue, n)]
    if rest:
        name = min(rest, key=lambda n: (factor.get(catalogue[n].group, 0.0), catalogue[n].price))
        return FundingStep(StepKind.MORTGAGE, name, catalogue[name].mortgage)
    return None


def apply_step(
    state: MonopolyState, catalogue: Mapping[str, Deed], me: Player, step: FundingStep
) -> MonopolyState:
    """手を状態に反映する(計画の確認用)。取引は、相手が受けた場合の結果。"""
    if step.kind is StepKind.MORTGAGE:
        return rules.mortgage(state, catalogue, me, step.name)
    if step.kind is StepKind.SELL_HOUSE:
        return rules.sell_house(state, catalogue, me, step.name)
    assert step.trade is not None
    return rules.apply_trade(state, catalogue, me, me.other(), step.trade)


def plan(
    state: MonopolyState,
    catalogue: Mapping[str, Deed],
    me: Player,
    needed: int,
    refused_trades: frozenset[str] = frozenset(),
) -> list[FundingStep]:
    """現金が needed 以上になるまでの手の列(取引は、すべて成立する仮定。実行時は 1 手ずつ確かめる)。"""
    steps: list[FundingStep] = []
    current = state
    while current.cash[me] < needed:
        step = next_step(current, catalogue, me, refused_trades)
        if step is None:
            break
        steps.append(step)
        current = apply_step(current, catalogue, me, step)
    return steps
