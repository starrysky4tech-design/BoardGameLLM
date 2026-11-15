"""鳥の能力の単体テスト。期待値は各札の文(birds.json の text。画像で確かめた分)から手で作る。

能力の効果関数を直接呼ぶものと、アプリと同じ決定の流れ(UsePower / SkipPower)で確かめるものがある。
"""

from dataclasses import replace

from bglm.plugins.wingspan.logic import powers
from bglm.plugins.wingspan.logic.cards import default_table
from bglm.plugins.wingspan.logic.goals import all_goal_tiles
from bglm.plugins.wingspan.logic.models import Food, Habitat, PlacedBird, Placement, PlayerBoard
from bglm.plugins.wingspan.logic.rules import WingspanRules
from bglm.plugins.wingspan.logic.state import (
    Decline,
    GainFood,
    LayEggs,
    PlayBird,
    SkipPower,
    TakeDie,
    TuckCard,
    TuckTask,
    UsePower,
    WingspanState,
)

TABLE = default_table()
RULES = WingspanRules(TABLE)
F, G, W = Habitat.FOREST, Habitat.GRASSLAND, Habitat.WETLAND
WARBLER = "クロズキンアメリカムシクイ"  # 森林、虫 2、7 点、能力なし、翼長 18
FILLER = "ミサゴ"  # 翼長 160(100 以上)
SMALL = "ヒメウタスズメ"  # 翼長 20(100 未満)


def board(forest=(), grass=(), wet=(), *, food=(0, 0, 0, 0, 0), hand=(), cubes=5) -> PlayerBoard:  # type: ignore[no-untyped-def]
    return PlayerBoard(
        rows=(tuple(forest), tuple(grass), tuple(wet)), food=food, hand=hand, cubes=cubes
    )


def state_of(*boards: PlayerBoard, **changes) -> WingspanState:  # type: ignore[no-untyped-def]
    base = WingspanState(
        players=boards,
        to_move=0,
        first_player=0,
        round_index=0,
        feeder=("fish", "fruit", "invertebrate", "rodent", "seed"),
        tray=("", "", ""),
        deck=tuple([WARBLER] * 10),
        discard=(),
        goals=all_goal_tiles()[:4],
    )
    return replace(base, **changes)


def run(state: WingspanState, bird: str, habitat: Habitat) -> WingspanState:
    """bird の能力を、その鳥を置いた行で効果関数を直接呼んで試す。"""
    power = TABLE.bird(bird).power
    at = Placement(habitat, 0)
    return powers.AUTO[power.kind](state, TABLE, 0, at, power)


def test_gain_supply_from_the_supply() -> None:
    # ショウジョウコウカンチョウ: 「あなたは共通在庫から果実を 1 個獲得する。」
    s = state_of(board(forest=[PlacedBird("ショウジョウコウカンチョウ")]), board())
    s = run(s, "ショウジョウコウカンチョウ", F)
    assert s.players[0].count(Food.FRUIT) == 1 and s.players[1].count(Food.FRUIT) == 0


def test_all_players_gain() -> None:
    # イスカ: 「各プレイヤーは共通在庫から種を 1 個ずつ獲得する。」
    s = state_of(board(forest=[PlacedBird("イスカ")]), board())
    s = run(s, "イスカ", F)
    assert s.players[0].count(Food.SEED) == 1 and s.players[1].count(Food.SEED) == 1


def test_all_players_draw_from_deck() -> None:
    # ハシビロガモ: 「各プレイヤーは鳥の山の上から 1 枚ずつ引く。」
    s = state_of(board(wet=[PlacedBird("ハシビロガモ")]), board())
    s = run(s, "ハシビロガモ", W)
    assert len(s.players[0].hand) == 1 and len(s.players[1].hand) == 1 and len(s.deck) == 8


def test_fewest_birds_in_habitat_draw() -> None:
    # ハシグロアビ: 湿地の鳥が最も少ない各プレイヤー(同数は全員)が山札から 1 枚引く
    s = state_of(board(wet=[PlacedBird("ハシグロアビ")]), board())
    s = run(s, "ハシグロアビ", W)
    assert len(s.players[0].hand) == 0 and len(s.players[1].hand) == 1  # 少ない相手だけ
    tied = run(
        state_of(board(wet=[PlacedBird("ハシグロアビ")]), board(wet=[PlacedBird(WARBLER)])),
        "ハシグロアビ",
        W,
    )
    assert len(tied.players[0].hand) == 1 and len(tied.players[1].hand) == 1  # 同数なら両方


def test_predator_tucks_small_bird_and_discards_large_one() -> None:
    # イヌワシ: 山札の一番上の翼長が 100cm 未満なら、この鳥の下に差し込む。そうでなければ捨て札
    eagle = board(grass=[PlacedBird("イヌワシ")])
    small = run(state_of(eagle, board(), deck=(SMALL, WARBLER)), "イヌワシ", G)
    assert small.players[0].birds()[0].tucked == 1 and small.discard == ()
    large = run(state_of(eagle, board(), deck=(FILLER, WARBLER)), "イヌワシ", G)
    assert large.players[0].birds()[0].tucked == 0 and large.discard == (FILLER,)


def test_predator_roll_caches_fish_about_as_often_as_dice_say() -> None:
    # クロハサミアジサシ: 餌箱の外のダイスを振り、魚が 1 つでもあれば魚を蓄える。
    # 餌箱に 1 個、外に 4 個 → 魚が出る確率は 1 − (5/6)^4 ≈ 0.52
    skimmer = board(wet=[PlacedBird("クロハサミアジサシ")])
    hits = sum(
        run(state_of(skimmer, board(), feeder=("seed",), seed=i), "クロハサミアジサシ", W)
        .players[0]
        .birds()[0]
        .cached
        for i in range(400)
    )
    assert 0.40 * 400 < hits < 0.64 * 400
    # 全部餌箱の中(外に 0 個)なら、振るダイスが無いので蓄えられない
    none = run(state_of(skimmer, board()), "クロハサミアジサシ", W)
    assert none.players[0].birds()[0].cached == 0


def test_feeder_cache_is_a_decision_and_needs_the_die() -> None:
    # シマセゲラ: 「餌箱から種を 1 個獲得する(餌箱にあるなら)。それをこの鳥の上に蓄えてもよい。」
    me = board(forest=[PlacedBird("シマセゲラ")])
    s = RULES.apply(state_of(me, board()), GainFood())
    s = RULES.apply(s, TakeDie(0, Food.FISH))  # 能力の前に餌を 1 個取る
    assert UsePower() in RULES.legal_moves(s)  # 種のダイスがあるので決定が出る
    used = RULES.apply(s, UsePower())
    assert used.players[0].birds()[0].cached == 1 and "seed" not in used.feeder
    # 餌箱に種が無ければ決定は出ず、そのまま手番が終わる
    no_seed = state_of(me, board(), feeder=("fish", "fruit"))
    no_seed = RULES.apply(RULES.apply(no_seed, GainFood()), TakeDie(0, Food.FISH))
    assert no_seed.to_move == 1


def test_discard_food_to_tuck_from_deck() -> None:
    # アカハシリュウキュウガモ: 「種を 1 個捨ててもよい。そうしたなら、鳥の山の上から 2 枚引き、この鳥の下に差し込む。」
    duck = board(wet=[PlacedBird("アカハシリュウキュウガモ")], food=(0, 1, 0, 0, 0))
    from bglm.plugins.wingspan.logic.state import DrawCards, TakeDeck

    s = RULES.apply(state_of(duck, board()), DrawCards())
    s = RULES.apply(s, TakeDeck())
    assert UsePower() in RULES.legal_moves(s)
    s = RULES.apply(s, UsePower())
    mine = s.players[0]
    assert mine.count(Food.SEED) == 0 and mine.birds()[0].tucked == 2
    # 山札 10 枚から、引いた 1 枚 + 差し込んだ 2 枚 + 手番の終わりのトレイの補充 3 枚(R p.9)が減る
    assert len(s.deck) == 10 - 1 - 2 - 3
    # 種が無ければ決定は出ない
    poor = board(wet=[PlacedBird("アカハシリュウキュウガモ")])
    s2 = RULES.apply(RULES.apply(state_of(poor, board()), DrawCards()), TakeDeck())
    assert s2.to_move == 1


def test_tuck_from_hand_then_gain_invertebrate() -> None:
    # コマツグミ: 手札から差し込んでもよい。そうしたなら虫を 1 個獲得する
    robin = board(forest=[PlacedBird("コマツグミ")], hand=(WARBLER,))
    s = RULES.apply(state_of(robin, board()), GainFood())
    s = RULES.apply(s, TakeDie(0, Food.FISH))
    s = RULES.apply(s, Decline())  # 札を捨てて餌を足す変換はしない
    assert UsePower() in RULES.legal_moves(s)
    s = RULES.apply(s, UsePower())
    assert isinstance(s.queue[0], TuckTask)
    s = RULES.apply(s, TuckCard(WARBLER))
    mine = s.players[0]
    assert mine.birds()[0].tucked == 1 and mine.hand == () and mine.count(Food.INVERTEBRATE) == 1


def test_tuck_from_hand_then_lay_when_played() -> None:
    # ヤブガラ(プレイ時): 手札から差し込んでもよい。そうしたなら、この鳥は卵を 1 個産卵し、この鳥の上に置く
    me = board(food=(1, 1, 0, 0, 0), hand=("ヤブガラ", WARBLER))
    s = state_of(me, board())
    play = next(
        m
        for m in RULES.legal_moves(s)
        if isinstance(m, PlayBird) and m.card == "ヤブガラ" and m.habitat is F
    )
    s = RULES.apply(s, play)
    assert UsePower() in RULES.legal_moves(s)  # プレイ時の能力の決定
    s = RULES.apply(RULES.apply(s, UsePower()), TuckCard(WARBLER))
    bird = s.players[0].birds()[0]
    assert (bird.tucked, bird.eggs) == (1, 1)
    # 手札が空なら決定は出ない(手番がそのまま終わる)
    bare = state_of(board(food=(1, 1, 0, 0, 0), hand=("ヤブガラ",)), board())
    play = next(m for m in RULES.legal_moves(bare) if isinstance(m, PlayBird) and m.habitat is F)
    assert RULES.apply(bare, play).to_move == 1


def test_skip_power_leaves_the_board_unchanged() -> None:
    # 能力はすべて任意(R p.10)。スキップすれば何も起きない
    duck = board(wet=[PlacedBird("アカハシリュウキュウガモ")], food=(0, 1, 0, 0, 0))
    from bglm.plugins.wingspan.logic.state import DrawCards, TakeDeck

    s = RULES.apply(RULES.apply(state_of(duck, board()), DrawCards()), TakeDeck())
    s = RULES.apply(s, SkipPower())
    assert s.players[0].count(Food.SEED) == 1 and s.players[0].birds()[0].tucked == 0


def test_unmodeled_power_is_skipped_without_a_decision() -> None:
    # 未実装の種類(ヒメウタスズメ: 別の生息地へ移す)は決定を出さず、効果なしで進む
    assert not powers.is_modeled(TABLE.bird("ヒメウタスズメ").power.kind)
    s = state_of(board(grass=[PlacedBird("ヒメウタスズメ")]), board())
    s = RULES.apply(s, LayEggs())
    while s.queue:
        s = RULES.apply(s, RULES.legal_moves(s)[0])
    assert s.to_move == 1
