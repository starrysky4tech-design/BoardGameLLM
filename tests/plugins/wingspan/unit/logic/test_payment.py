"""餌の払い方の単体テスト。期待値は R p.6 の記述から手で作る。

餌の並びは (虫, 種, 魚, 果実, ネズミ)。
"""

from bglm.plugins.wingspan.logic.models import Food, FoodCost
from bglm.plugins.wingspan.logic.payment import minimal_payments, payments

INV, SEED, FISH, FRUIT, ROD = Food.INVERTEBRATE, Food.SEED, Food.FISH, Food.FRUIT, Food.RODENT


def test_no_cost_pays_nothing() -> None:
    # R p.6: 斜線の丸(餌のコスト無し)は何も払わない
    assert payments((0, 0, 0, 0, 0), FoodCost()) == [(0, 0, 0, 0, 0)]


def test_all_required_foods_must_be_paid() -> None:
    # R p.6: 「+」は全部払う。手元に無ければ払えない
    cost = FoodCost(foods=(FISH, SEED))
    assert minimal_payments((0, 1, 1, 0, 0), cost) == [(0, 1, 1, 0, 0)]
    assert payments((0, 1, 0, 0, 0), cost) == []


def test_either_pays_one_of_the_listed_foods() -> None:
    # R p.6: 「/」はどちらか 1 つ(果実 / 虫)。両方持っていれば払い方は 2 通り
    cost = FoodCost(foods=(FRUIT, INV), either=True)
    assert minimal_payments((1, 0, 0, 1, 0), cost) == [(0, 0, 0, 1, 0), (1, 0, 0, 0, 0)]


def test_wild_accepts_any_food() -> None:
    # R p.6: wild はどの餌でもよい(ヤマセミ: wild + 魚)
    cost = FoodCost(foods=(FISH,), wild=1)
    assert minimal_payments((0, 2, 1, 0, 0), cost) == [(0, 1, 1, 0, 0)]


def test_two_foods_can_replace_one_when_playing() -> None:
    # R p.6: 魚が要るとき、他の餌 2 個で代えられる
    cost = FoodCost(foods=(FISH,))
    options = payments((0, 1, 0, 1, 0), cost)
    assert (0, 1, 0, 1, 0) in options  # 種 1 + 果実 1


def test_two_foods_of_same_kind_can_replace_one() -> None:
    # 同じ餌 2 個でもよい(「任意の餌 2 個」)
    cost = FoodCost(foods=(FISH,))
    assert (0, 2, 0, 0, 0) in payments((0, 2, 0, 0, 0), cost)


def test_cannot_pay_if_total_is_not_enough() -> None:
    # 餌 1 個しか無ければ、魚(1 個)は 2 個で代えられないので払えない
    assert payments((0, 1, 0, 0, 0), FoodCost(foods=(FISH,))) == []


def test_minimal_payments_keep_incomparable_options() -> None:
    # 魚 1 個で払う方法と、魚を残して虫 + 種で払う方法は、どちらも他方を含まないので両方残る
    # (どちらが得かは思考の仕事)
    cost = FoodCost(foods=(FISH,))
    assert minimal_payments((1, 1, 1, 0, 0), cost) == [(0, 0, 1, 0, 0), (1, 1, 0, 0, 0)]


def test_minimal_payments_drop_supersets() -> None:
    # 「魚 1 個」で払えるなら、「魚 1 個 + 余分な餌」の払い方は出さない(余分に払うだけで得が無い)
    cost = FoodCost(foods=(FISH,), wild=1)
    options = minimal_payments((0, 0, 2, 0, 0), cost)
    assert options == [(0, 0, 2, 0, 0)]
