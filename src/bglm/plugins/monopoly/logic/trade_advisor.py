"""相手から提示された取引への応答(受ける・断る・対案を出す)。画面には依存しない。

基準(2026-11-08 の指示。優先順):
 1. 自分だけの土地が全て揃う(相手は揃わない)、または鉄道・会社の収入が増える → 受ける
 2. 自分も相手も土地が全て揃うが、自分の土地の評価が高い → 受ける
    「土地の評価」は、土地の価格ではなく、止まりやすさと、建設費に対する収益の良さ(`group_return_factor`)
 3. 相手だけが土地・鉄道が揃う → 1 枚 : 1 枚では受けず、1 枚 : 2 枚(+ お金)、1 枚 : 3 枚(+ お金)の対案で交渉
 絶対的に自分が不利な場合は、断る

受ける条件に当てはまっても、資産の差(自分 − 相手)が減る取引は受けない(絶対的に不利な取引の除外)。
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from itertools import combinations

from bglm.plugins.monopoly.logic import rules
from bglm.plugins.monopoly.logic.models import Deed, DeedKind, MonopolyState, Player, Trade
from bglm.plugins.monopoly.logic.policies import ExpectedValuePolicy, group_return_factor

COUNTER_DEED_COUNTS = (2, 3)  # 対案で、相手から求める土地の数(自分が渡すのは、提示された土地)
COUNTER_CASH_SHARE = 0.5  # 対案で、相手の現金のうち、求める割合(暫定。相手が受けるかは、分からない)


class Verdict(Enum):
    ACCEPT = "accept"
    DECLINE = "decline"
    COUNTER = "counter"


@dataclass(frozen=True)
class TradeDecision:
    verdict: Verdict
    reason: str
    counter: Trade | None = None  # COUNTER のときの対案(自分を proposer とした向き)


def complete_groups(
    state: MonopolyState, catalogue: Mapping[str, Deed], player: Player
) -> set[str]:
    """その色の街を、全て持つ色グループ(抵当中でも、持っていれば数える)。"""
    groups: set[str] = set()
    for deed in catalogue.values():
        if deed.kind is DeedKind.STREET and rules.owns_full_group(state, catalogue, player, deed):
            groups.add(deed.group)
    return groups


def transport_count(
    state: MonopolyState, catalogue: Mapping[str, Deed], player: Player
) -> tuple[int, int]:
    """(鉄道の数, 会社の数)。"""
    return (
        rules.owned_of_kind(state, catalogue, player, DeedKind.RAILROAD),
        rules.owned_of_kind(state, catalogue, player, DeedKind.UTILITY),
    )


def decide_trade(
    state: MonopolyState,
    catalogue: Mapping[str, Deed],
    me: Player,
    proposer: Player,
    trade: Trade,
    policy: ExpectedValuePolicy | None = None,
) -> TradeDecision:
    """相手(proposer)が提示した取引への応答。trade の proposer 側が相手、partner 側が自分。"""
    policy = policy or ExpectedValuePolicy()
    try:
        after = rules.apply_trade(state, catalogue, proposer, me, trade)
    except ValueError as error:
        return TradeDecision(Verdict.DECLINE, f"成立しない取引: {error}")

    opponent = me.other()
    factor = group_return_factor()
    my_new = complete_groups(after, catalogue, me) - complete_groups(state, catalogue, me)
    ai_new = complete_groups(after, catalogue, opponent) - complete_groups(
        state, catalogue, opponent
    )
    before_transport = transport_count(state, catalogue, me)
    after_transport = transport_count(after, catalogue, me)
    income_up = any(a > b for a, b in zip(after_transport, before_transport, strict=True))
    margin = policy.margin_gain(state, after, catalogue, me)

    if (my_new or income_up) and not ai_new:
        if margin >= 0:
            return TradeDecision(
                Verdict.ACCEPT,
                f"自分だけが揃う/収入が増える(揃う: {sorted(my_new)}、鉄道・会社 {before_transport}→{after_transport})",
            )
        return TradeDecision(Verdict.DECLINE, f"揃うが、資産の差が {margin:.0f} 減る(不利)")

    if my_new and ai_new:
        mine = sum(factor[g] for g in my_new)
        theirs = sum(factor[g] for g in ai_new)
        if mine > theirs and margin >= 0:
            return TradeDecision(
                Verdict.ACCEPT, f"双方が揃うが、自分の土地の評価が高い({mine:.2f} > {theirs:.2f})"
            )
        return TradeDecision(
            Verdict.DECLINE, f"双方が揃うが、自分の評価が高くない({mine:.2f} <= {theirs:.2f})"
        )

    if ai_new and not my_new:
        # 提示がすでに、1 枚 : 2 枚以上(+ お金)で、資産の差が増えるなら、そのまま受ける(基準 3 を満たしている)
        if (
            trade.partner_deeds
            and len(trade.proposer_deeds) >= 2 * len(trade.partner_deeds)
            and margin > policy.trade_margin
        ):
            return TradeDecision(
                Verdict.ACCEPT,
                f"相手だけが揃う({sorted(ai_new)})が、1 : {len(trade.proposer_deeds)} の提示で、資産の差が {margin:.0f} 増える",
            )
        counter = _counter_offer(state, catalogue, me, proposer, trade, policy)
        if counter is not None:
            return TradeDecision(
                Verdict.COUNTER,
                f"相手だけが揃う({sorted(ai_new)})。1 枚 : 複数枚(+ お金)で交渉",
                counter,
            )
        return TradeDecision(Verdict.DECLINE, f"相手だけが揃う({sorted(ai_new)})。対案も立たない")

    # 独占に関わらない取引は、資産の差が増えるときだけ受ける(既存の方針と同じ)
    if margin > policy.trade_margin:
        return TradeDecision(Verdict.ACCEPT, f"独占に関わらないが、資産の差が {margin:.0f} 増える")
    return TradeDecision(Verdict.DECLINE, f"資産の差が {margin:.0f}(得にならない)")


def _counter_offer(
    state: MonopolyState,
    catalogue: Mapping[str, Deed],
    me: Player,
    proposer: Player,
    trade: Trade,
    policy: ExpectedValuePolicy,
) -> Trade | None:
    """相手だけが揃う取引への対案。自分が渡す土地は、相手が欲しがる土地(提示と同じ)のまま、
    相手から 2 枚、3 枚(+ お金)を求める。自分(me)を proposer とした取引で返す。

    相手の土地は、家が建っていない土地だけ(家が建つグループは、取引できない)。求める土地の組は、
    取引後の自分の資産の差が最も増える組を選ぶ。お金は、相手の現金の一部。
    """
    opponent = proposer
    give = trade.partner_deeds  # 自分が渡す土地
    candidates = [
        name
        for name, holding in state.holdings.items()
        if holding.owner is opponent and name not in trade.proposer_deeds
    ]
    cash = int(state.cash[opponent] * COUNTER_CASH_SHARE) // 10 * 10
    best: tuple[float, Trade] | None = None
    for count in COUNTER_DEED_COUNTS:
        for deeds in combinations(sorted(candidates), count):
            offer = Trade(
                proposer_deeds=give,
                proposer_cash=trade.partner_cash,
                partner_deeds=frozenset(deeds),
                partner_cash=cash,
            )
            if not rules.can_trade(state, catalogue, me, opponent, offer):
                continue
            after = rules.apply_trade(state, catalogue, me, opponent, offer)
            margin = policy.margin_gain(state, after, catalogue, me)
            if margin > policy.trade_margin and (best is None or margin > best[0]):
                best = (margin, offer)
    return best[1] if best else None
