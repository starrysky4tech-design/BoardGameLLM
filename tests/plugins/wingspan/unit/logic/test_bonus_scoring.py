"""ボーナスカードと最終得点の単体テスト。期待値は付録(A p.4〜5)とルールブック(R p.5)から手で作る。

札は「その基準を試すのに要る値だけ」を持つ最小の BirdCard。実在の札の値ではない。
"""

from bglm.plugins.wingspan.logic.bonus import BonusCard, bonus_points, count_bonus
from bglm.plugins.wingspan.logic.models import (
    BirdCard,
    Food,
    FoodCost,
    Habitat,
    Nest,
    PlacedBird,
    PlayerBoard,
)
from bglm.plugins.wingspan.logic.scoring import ScoreBreakdown, score_board, winner

F, G, W = Habitat.FOREST, Habitat.GRASSLAND, Habitat.WETLAND
NO_COST = FoodCost()


def bird(
    name: str,
    habitats: tuple[Habitat, ...] = (F,),
    *,
    points: int = 2,
    nest: Nest = Nest.BOWL,
    wingspan: int = 40,
    cost: FoodCost = NO_COST,
    name_en: str = "",
    flocking: bool = False,
    predator: bool = False,
) -> BirdCard:
    return BirdCard(
        name=name,
        habitats=frozenset(habitats),
        cost=cost,
        points=points,
        nest=nest,
        egg_limit=3,
        wingspan_cm=wingspan,
        name_en=name_en,
        flocking=flocking,
        predator=predator,
    )


def table(*cards: BirdCard):  # type: ignore[no-untyped-def]
    by_name = {c.name: c for c in cards}
    return by_name.__getitem__


def board_of(*names: str, hand: tuple[str, ...] = (), rows: tuple[int, int, int] = (0, 0, 0)):  # type: ignore[no-untyped-def]
    """names を森林の行に並べた盤。rows を渡すと、その数だけ各行に同じ札を並べる。"""
    if any(rows):
        return PlayerBoard(
            rows=tuple(tuple(PlacedBird(names[0]) for _ in range(n)) for n in rows),  # type: ignore[arg-type]
            hand=hand,
        )
    return PlayerBoard(rows=(tuple(PlacedBird(n) for n in names), (), ()), hand=hand)


def test_large_bird_specialist_excludes_exactly_65() -> None:
    # A p.5: 翼長が 65cm を超える鳥。ちょうど 65cm は数えない
    lookup = table(bird("a", wingspan=65), bird("b", wingspan=66))
    card = BonusCard("大型鳥", "wingspan_over", "65", per_item=2)
    assert count_bonus(card, board_of("a", "b"), lookup) == 1


def test_passerine_specialist_includes_exactly_30() -> None:
    # A p.5: 翼長が 30cm 以下。ちょうど 30cm は数える
    lookup = table(bird("a", wingspan=30), bird("b", wingspan=31))
    card = BonusCard("小型鳥", "wingspan_at_most", "30", per_item=2)
    assert count_bonus(card, board_of("a", "b"), lookup) == 1


def test_backyard_birder_counts_zero_to_three_points() -> None:
    # A p.5: 点が 0、1、2、3 の鳥(4 点は数えない)
    lookup = table(bird("a", points=3), bird("b", points=4), bird("c", points=0))
    card = BonusCard("裏庭の鳥", "points_below", "4", per_item=1)
    assert count_bonus(card, board_of("a", "b", "c"), lookup) == 2


def test_visionary_leader_counts_hand() -> None:
    # A p.5: 終了時に手札に残っている鳥カードの数
    card = BonusCard("先見の指導者", "hand_size", per_item=1)
    assert count_bonus(card, board_of(hand=("x", "y", "z")), table()) == 3


def test_ecologist_uses_fewest_habitat_even_when_tied() -> None:
    # A p.5: 最も鳥の少ない生息地の鳥の数。3 つとも 3 羽なら 3(同数でも得点できる)
    lookup = table(bird("a"))
    card = BonusCard("生態学者", "fewest_habitat", per_item=1)
    assert count_bonus(card, board_of("a", rows=(3, 3, 3)), lookup) == 3
    assert count_bonus(card, board_of("a", rows=(3, 1, 4)), lookup) == 1


def test_single_habitat_birds_exclude_multi_habitat() -> None:
    # A p.5: 1 つの生息地にだけ住む鳥。複数の生息地を持つ鳥は数えない
    lookup = table(bird("a", (F,)), bird("b", (F, G)))
    card = BonusCard("森林学者", "habitat_only", "forest", per_item=2)
    assert count_bonus(card, board_of("a", "b"), lookup) == 1


def test_nest_bonus_star_is_wild() -> None:
    # A p.5: 星の巣はどの巣の種類のボーナスにも数える
    lookup = table(
        bird("a", nest=Nest.PLATFORM), bird("b", nest=Nest.STAR), bird("c", nest=Nest.BOWL)
    )
    card = BonusCard("皿の建築家", "nest", "platform", per_item=2)
    assert count_bonus(card, board_of("a", "b", "c"), lookup) == 2


def test_egg_bonuses_use_final_eggs() -> None:
    # A p.5: 卵 4 個以上の鳥 / 卵が 1 個以上の鳥
    lookup = table(bird("a"))
    board = PlayerBoard(
        rows=((PlacedBird("a", eggs=4), PlacedBird("a", eggs=1), PlacedBird("a")), (), ())
    )
    assert (
        count_bonus(BonusCard("繁殖管理者", "eggs_at_least", "4", per_item=1), board, lookup) == 1
    )
    assert count_bonus(BonusCard("卵学者", "eggs_at_least", "1", per_item=1), board, lookup) == 2


def test_food_bonus_counts_symbol_even_when_cost_is_either() -> None:
    # A p.5: 「種 / 果実」の鳥は、種のボーナスにも果実のボーナスにも数える(実際に何を払ったかは問わない)
    either = FoodCost(foods=(Food.SEED, Food.FRUIT), either=True)
    lookup = table(bird("a", cost=either), bird("b", cost=FoodCost(foods=(Food.FISH,))))
    assert (
        count_bonus(BonusCard("x", "food_symbol", "seed", per_item=1), board_of("a", "b"), lookup)
        == 1
    )
    assert (
        count_bonus(BonusCard("x", "food_symbol", "fruit", per_item=1), board_of("a", "b"), lookup)
        == 1
    )
    assert (
        count_bonus(BonusCard("x", "food_symbol", "fish", per_item=1), board_of("a", "b"), lookup)
        == 1
    )


def test_omnivore_counts_wild_only() -> None:
    # A p.5: 「何でも」の印は雑食の専門家にだけ数える
    lookup = table(bird("a", cost=FoodCost(wild=1)), bird("b", cost=FoodCost(foods=(Food.SEED,))))
    assert (
        count_bonus(
            BonusCard("雑食", "food_symbol", "wild", per_item=2), board_of("a", "b"), lookup
        )
        == 1
    )
    assert (
        count_bonus(BonusCard("x", "food_symbol", "seed", per_item=1), board_of("a", "b"), lookup)
        == 1
    )


def test_name_bonus_needs_english_name() -> None:
    # A p.4: 色の名前の鳥(1 羽は 1 回だけ)。英語名が無い札は数えない(推測しない)
    lookup = table(
        bird("a", name_en="Yellow-rumped Warbler"),  # yellow だけ(rump は部位)。色としては 1 回
        bird("b", name_en="Black-capped Chickadee"),
        bird("c", name_en=""),
        bird("d", name_en="Song Sparrow"),
    )
    card = BonusCard("写真家", "name", "color", per_item=1)
    assert count_bonus(card, board_of("a", "b", "c", "d"), lookup) == 2


def test_anatomy_counts_inflected_forms() -> None:
    # A p.4: 部位の語は活用形(bellied など)も数える
    lookup = table(bird("a", name_en="Red-bellied Woodpecker"), bird("b", name_en="Song Sparrow"))
    card = BonusCard("解剖学者", "name", "anatomy", per_item=1)
    assert count_bonus(card, board_of("a", "b"), lookup) == 1


def test_anatomy_matches_whole_words_only() -> None:
    # 部分一致だと Cape May の「cap」を部位と誤る。単語単位で照合する(活用形 capped は数える)
    lookup = table(
        bird("a", name_en="Cape May Warbler"),
        bird("b", name_en="Black-capped Chickadee"),
        bird("c", name_en="Ruby-throated Hummingbird"),
    )
    card = BonusCard("解剖学者", "name", "anatomy", per_item=1)
    assert count_bonus(card, board_of("a", "b", "c"), lookup) == 2


def test_historian_counts_possessive() -> None:
    # A p.4: 人名(’s を含む)
    lookup = table(bird("a", name_en="Anna’s Hummingbird"), bird("b", name_en="Song Sparrow"))
    card = BonusCard("歴史家", "name", "person", per_item=1)
    assert count_bonus(card, board_of("a", "b"), lookup) == 1


def test_bonus_points_per_item_and_tiers() -> None:
    assert bonus_points(BonusCard("x", "hand_size", per_item=2), 4) == 8
    tiered = BonusCard("y", "hand_size", tiers=((2, 3, 3), (4, 99, 7)))
    assert [bonus_points(tiered, n) for n in (0, 1, 2, 3, 4, 9)] == [0, 0, 3, 3, 7, 7]


def test_score_breakdown_matches_the_app_screens() -> None:
    # アプリの終局の詳細(RESULT.md §10 の実測): 自分 鳥 19 / ボーナス 1 / 目的 7 / 卵 17 / 餌 7 / 札 1 → 52、
    # 相手 27 / 0 / 18 / 18 / 0 / 0 → 63
    assert ScoreBreakdown(19, 1, 7, 17, 7, 1).total == 52
    assert ScoreBreakdown(27, 0, 18, 18, 0, 0).total == 63


def test_score_board_sums_every_component() -> None:
    lookup = table(bird("a", points=5), bird("b", points=3))
    board = PlayerBoard(
        rows=((PlacedBird("a", eggs=2, cached=1, tucked=3), PlacedBird("b", eggs=1)), (), ()),
        bonus=("名無し", "手札"),
        hand=("x", "y"),
        goal_points=(4, 1),
    )
    bonus = {"手札": BonusCard("手札", "hand_size", per_item=1)}  # 表に無い「名無し」は 0 点
    got = score_board(board, lookup, bonus)
    assert got == ScoreBreakdown(birds=8, bonus=2, goals=5, eggs=3, cached=1, tucked=3)
    assert got.total == 22


def test_winner_tie_breaks_by_unused_food() -> None:
    # R p.5: 同点は、使っていない餌が多い方が勝つ。それでも同点なら共同勝利
    rich = PlayerBoard(food=(2, 0, 0, 0, 0))
    poor = PlayerBoard(food=(1, 0, 0, 0, 0))
    assert winner((rich, poor), (50, 50)) == [0]
    assert winner((rich, rich), (50, 50)) == [0, 1]
    assert winner((rich, poor), (49, 50)) == [1]
