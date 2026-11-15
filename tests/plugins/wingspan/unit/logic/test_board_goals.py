"""マットの数値と目的タイルの採点の単体テスト。期待値はルールブック(R)と付録(A)から手で作る。

出典の表記: R p.n = ルールブック(WS_Rulebook_r24)の印刷ページ、A p.n = 付録(WS_Appendix_r17)。
行動の強さの表は、アプリの全体ボードの 6 つの枠(RESULT.md §2)で確かめた値。
"""

import pytest

from bglm.plugins.wingspan.logic.board import (
    ROUNDS,
    TURNS_PER_ROUND,
    action_strength,
    egg_cost,
)
from bglm.plugins.wingspan.logic.goals import (
    GoalMode,
    GoalTile,
    all_goal_tiles,
    count_goal,
    goal_points,
    majority_points,
    per_item_points,
)
from bglm.plugins.wingspan.logic.models import Habitat, Nest, PlacedBird, PlayerBoard

NESTS = {"皿": Nest.PLATFORM, "椀": Nest.BOWL, "星": Nest.STAR}


def nest_of(name: str) -> Nest:
    return NESTS[name]


def board(forest=(), grass=(), wet=()) -> PlayerBoard:  # type: ignore[no-untyped-def]
    return PlayerBoard(rows=(tuple(forest), tuple(grass), tuple(wet)))


def test_turns_per_round() -> None:
    # R p.5: 8、7、6、5 手番
    assert TURNS_PER_ROUND == (8, 7, 6, 5)
    assert ROUNDS == 4


@pytest.mark.parametrize(
    ("birds_in_row", "cost"), [(0, 0), (1, 1), (2, 1), (3, 2), (4, 2), (5, None)]
)
def test_egg_cost(birds_in_row: int, cost: int | None) -> None:
    # R p.6: 1 列目は 0、2〜3 列目は卵 1 個、4〜5 列目は卵 2 個。1 つの生息地に置ける鳥は 5 羽まで
    assert egg_cost(birds_in_row) == cost


def test_action_strength_tables() -> None:
    # 鳥が 0〜5 羽のときの (個数, 変換あり)。変換は 1 羽おきの枠(RESULT.md §2 の全体ボード)
    forest = [action_strength(Habitat.FOREST, n) for n in range(6)]
    assert forest == [(1, False), (1, True), (2, False), (2, True), (3, False), (3, True)]
    grass = [action_strength(Habitat.GRASSLAND, n) for n in range(6)]
    assert grass == [(2, False), (2, True), (3, False), (3, True), (4, False), (4, True)]
    wet = [action_strength(Habitat.WETLAND, n) for n in range(6)]
    assert wet == [(1, False), (1, True), (2, False), (2, True), (3, False), (3, True)]


def test_sixteen_goal_tiles() -> None:
    # A p.3: 生息地の鳥 3 + 巣の卵のある鳥 4 + 生息地の卵 3 + 巣の卵 4 + 卵の組 1 + 鳥の総数 1
    assert len(all_goal_tiles()) == 16


@pytest.mark.parametrize(("round_index", "first"), [(0, 4), (1, 5), (2, 6), (3, 7)])
def test_majority_first_place_points(round_index: int, first: int) -> None:
    # R p.1 の目的ボード: 1 位は 4、5、6、7 点
    assert majority_points([3, 1], round_index)[0] == first


def test_majority_tie_for_first_example_from_rulebook() -> None:
    # R p.11: 「5、2、1 点の目的で、2 人が 1 位で並んだら、各 3 点(5 + 2 を 2 人で割る)。2 位は誰にも与えない」
    # 残る 1 人は 3 位なので 3 位の点(1)。「2 位を与えない」とは、その人を 2 位にしないこと
    assert majority_points([4, 4, 1], 1) == [3, 3, 1]


def test_majority_tie_rounds_down() -> None:
    # R p.11: 切り捨て。ラウンド 3(6/3/2)で 2 位が 2 人: (3 + 2) // 2 = 2
    assert majority_points([5, 3, 3], 2) == [6, 2, 2]


def test_majority_must_have_at_least_one() -> None:
    # R p.11: 対象を 1 つも持たなければ点は入らない(0 同士で並んでも 0 点)
    assert majority_points([0, 0], 3) == [0, 0]
    assert majority_points([2, 0], 3) == [7, 0]


def test_majority_fourth_place_scores_zero() -> None:
    # R p.11: 4 位・5 位は 0 点(ラウンド 1)
    assert majority_points([5, 4, 3, 2], 0) == [4, 1, 0, 0]


def test_per_item_caps_at_five() -> None:
    # R p.11: 青の面は 1 個 1 点、最大 5 点
    assert per_item_points([7, 3, 0]) == [5, 3, 0]


def test_egg_sets_example_from_appendix() -> None:
    # A p.3: 森林に卵 3、草原に卵 2、湿地に卵 4 → 2 組。どの鳥・どの列にあるかは問わない
    b = board(
        forest=[PlacedBird("椀", eggs=3)],
        grass=[PlacedBird("椀", eggs=1), PlacedBird("椀", eggs=1)],
        wet=[PlacedBird("椀", eggs=4)],
    )
    assert count_goal(GoalTile("egg_sets"), b, nest_of) == 2


def test_nest_birds_with_eggs_counts_each_bird_once_and_star_is_wild() -> None:
    # A p.3: 卵のある鳥を 1 羽ずつ数える(卵の数は問わない)。星の巣はどの種類にも数える
    b = board(
        forest=[PlacedBird("椀", eggs=3), PlacedBird("椀", eggs=0)],
        grass=[PlacedBird("星", eggs=1), PlacedBird("皿", eggs=2)],
    )
    assert count_goal(GoalTile("nest_birds_with_eggs", "bowl"), b, nest_of) == 2  # 椀 1 + 星 1
    assert count_goal(GoalTile("nest_birds_with_eggs", "platform"), b, nest_of) == 2  # 皿 1 + 星 1


def test_eggs_in_nest_counts_every_egg() -> None:
    # A p.3: 卵は 1 個ずつ数える(星の巣を含む)
    b = board(forest=[PlacedBird("椀", eggs=3)], grass=[PlacedBird("星", eggs=2)])
    assert count_goal(GoalTile("eggs_in_nest", "bowl"), b, nest_of) == 5


def test_habitat_goals() -> None:
    # A p.3: 生息地の鳥の数 / 生息地の卵の数
    b = board(
        forest=[PlacedBird("椀", eggs=2), PlacedBird("椀", eggs=1)],
        wet=[PlacedBird("皿")],
    )
    assert count_goal(GoalTile("birds_in_habitat", "forest"), b, nest_of) == 2
    assert count_goal(GoalTile("eggs_in_habitat", "forest"), b, nest_of) == 3
    assert count_goal(GoalTile("total_birds"), b, nest_of) == 3


def test_goal_points_uses_mode() -> None:
    a = board(forest=[PlacedBird("椀"), PlacedBird("椀")])
    b = board(forest=[PlacedBird("椀")])
    tile = GoalTile("birds_in_habitat", "forest")
    assert goal_points(tile, (a, b), 0, GoalMode.MAJORITY, nest_of) == [4, 1]
    assert goal_points(tile, (a, b), 0, GoalMode.PER_ITEM, nest_of) == [2, 1]
