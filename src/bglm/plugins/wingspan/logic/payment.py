"""鳥のプレイの餌の払い方の列挙(出典: ルールブック R p.6)。

- 「+」は全部払う。「/」はどれか 1 つ。「何でも」(wild)は任意の餌 1 個
- **鳥のプレイのときだけ**、任意の餌 2 個を、必要な餌 1 個の代わりにできる(他の場面では使えない)
- 払えるのは手元の餌だけ(札に蓄えた餌は払えない)

払い方は「餌ごとの払う個数」の組(FOODS の並び)で表す。重複は除く。
"""

from itertools import combinations_with_replacement

from bglm.plugins.wingspan.logic.models import FOODS, Food, FoodCost

Spend = tuple[int, int, int, int, int]  # FOODS の並びで、払う個数


def _requirements(cost: FoodCost) -> list[list[Food | None]]:
    """必要な餌の並びの候補。None は wild。「/」は選び方の数だけ候補ができる。"""
    if cost.either:
        return [[f] for f in cost.foods]
    return [[*cost.foods, *([None] * cost.wild)]]


def _pay(reqs: list[Food | None], have: list[int], spend: list[int], out: set[Spend]) -> None:
    if not reqs:
        out.add((spend[0], spend[1], spend[2], spend[3], spend[4]))
        return
    req, rest = reqs[0], reqs[1:]
    if req is None:
        # wild: 手元の任意の餌 1 個(2 個で 1 個の交換は、wild には要らない)
        for food in FOODS:
            i = FOODS.index(food)
            if have[i] > 0:
                have[i] -= 1
                spend[i] += 1
                _pay(rest, have, spend, out)
                have[i] += 1
                spend[i] -= 1
        return
    i = FOODS.index(req)
    if have[i] > 0:
        have[i] -= 1
        spend[i] += 1
        _pay(rest, have, spend, out)
        have[i] += 1
        spend[i] -= 1
    # 交換: 任意の餌 2 個で 1 個の代わり(R p.6)
    for a, b in combinations_with_replacement(FOODS, 2):
        ia, ib = FOODS.index(a), FOODS.index(b)
        need_a = 2 if ia == ib else 1
        if have[ia] >= need_a and (ia == ib or have[ib] >= 1):
            have[ia] -= 1
            have[ib] -= 1
            spend[ia] += 1
            spend[ib] += 1
            _pay(rest, have, spend, out)
            have[ia] += 1
            have[ib] += 1
            spend[ia] -= 1
            spend[ib] -= 1


def payments(food: tuple[int, int, int, int, int], cost: FoodCost) -> list[Spend]:
    """払える餌の組をすべて返す(払えなければ空)。コストが無ければ「何も払わない」の 1 つ。"""
    out: set[Spend] = set()
    for reqs in _requirements(cost):
        _pay(list(reqs), list(food), [0] * 5, out)
    return sorted(out)


def minimal_payments(food: tuple[int, int, int, int, int], cost: FoodCost) -> list[Spend]:
    """他の払い方に「余分に払っただけ」のものを除く。交換で餌を無駄にする払い方を思考に出さないため。"""
    all_options = payments(food, cost)
    return [
        s
        for s in all_options
        if not any(t != s and all(t[i] <= s[i] for i in range(5)) for t in all_options)
    ]
