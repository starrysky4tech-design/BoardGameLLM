"""手番の進行の単体テスト。期待値はルールブック(R)と付録(A)の記述から手で作る。

札は実在の表の札を使う(値は birds.json。画像で確かめた分)。使う札:
- クロズキンアメリカムシクイ: 森林、虫 2、7 点、卵 3、能力なし
- カンムリウズラ: 森林・草原、虫 + 種 2、卵 6、起動時に自分へ卵 1 個
- アメリカヤマセミ: 湿地、魚 + 何でも、桃色(他者が湿地の鳥をプレイしたら魚 1 個)
- イスカ: 森林、種 2、起動時に全員が種 1 個
"""

from dataclasses import replace

from bglm.plugins.wingspan.logic.cards import default_table
from bglm.plugins.wingspan.logic.goals import all_goal_tiles
from bglm.plugins.wingspan.logic.models import Food, Habitat, PlacedBird, Placement, PlayerBoard
from bglm.plugins.wingspan.logic.powers import trigger_pink
from bglm.plugins.wingspan.logic.rules import WingspanRules
from bglm.plugins.wingspan.logic.state import (
    ConvertCard,
    Decline,
    DrawCards,
    GainFood,
    GainFoodTask,
    LayEgg,
    LayEggs,
    PlayBird,
    Reroll,
    TakeDie,
    TakeTray,
    WingspanState,
)

TABLE = default_table()
RULES = WingspanRULES = WingspanRules(TABLE)
WARBLER = "クロズキンアメリカムシクイ"
QUAIL = "カンムリウズラ"
KINGFISHER = "アメリカヤマセミ"
CROSSBILL = "イスカ"
F, G, W = Habitat.FOREST, Habitat.GRASSLAND, Habitat.WETLAND
DICE = ("fish", "fruit", "invertebrate", "rodent", "seed")


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
        feeder=DICE,
        tray=("", "", ""),
        deck=tuple([WARBLER] * 10),
        discard=(),
        goals=all_goal_tiles()[:4],
    )
    return replace(base, **changes)


def test_playing_in_second_column_costs_one_egg() -> None:
    # R p.6: 2〜3 列目は卵 1 個。卵はどの鳥から払ってもよい。餌のコストも払う
    me = board(forest=[PlacedBird(WARBLER, eggs=1)], food=(2, 0, 0, 0, 0), hand=(WARBLER,))
    s = state_of(me, board())
    moves = [m for m in RULES.legal_moves(s) if isinstance(m, PlayBird)]
    assert moves and all(len(m.egg_from) == 1 for m in moves)
    after = RULES.apply(s, moves[0])
    mine = after.players[0]
    assert len(mine.row(F)) == 2
    assert mine.birds()[0].eggs == 0  # 卵を払った
    assert mine.food == (0, 0, 0, 0, 0)  # 虫 2 を払った
    assert mine.hand == () and mine.cubes == 4  # キューブを 1 個使う
    assert after.to_move == 1  # 手番が移る


def test_cannot_play_without_the_egg_or_food() -> None:
    # R p.6: コストを全部払えなければプレイできない
    no_egg = board(forest=[PlacedBird(WARBLER)], food=(2, 0, 0, 0, 0), hand=(WARBLER,))
    assert not [m for m in RULES.legal_moves(state_of(no_egg, board())) if isinstance(m, PlayBird)]
    no_food = board(hand=(WARBLER,))
    assert not [m for m in RULES.legal_moves(state_of(no_food, board())) if isinstance(m, PlayBird)]


def test_cannot_play_in_a_full_row() -> None:
    # R p.6: 1 つの生息地に置ける鳥は 5 羽まで
    full = board(forest=[PlacedBird(WARBLER, eggs=3)] * 5, food=(2, 0, 0, 0, 0), hand=(WARBLER,))
    assert not [m for m in RULES.legal_moves(state_of(full, board())) if isinstance(m, PlayBird)]


def test_gain_food_then_discard_card_for_extra_die() -> None:
    # R p.7: 2 列目(鳥 1 羽)は餌 1 個 + 札 1 枚を捨てて餌をもう 1 個。追加の餌も餌箱のダイスから取る
    me = board(forest=[PlacedBird(WARBLER)], hand=(WARBLER,))
    s = RULES.apply(state_of(me, board()), GainFood())
    assert isinstance(s.queue[0], GainFoodTask) and s.queue[0].convert
    s = RULES.apply(s, TakeDie(0, Food.FISH))  # 魚のダイスを取る
    assert s.players[0].count(Food.FISH) == 1
    assert "fish" not in s.feeder
    s = RULES.apply(s, ConvertCard(WARBLER))
    assert s.players[0].hand == () and s.discard == (WARBLER,)
    s = RULES.apply(s, TakeDie(0, Food.FRUIT))
    assert s.players[0].food == (0, 0, 1, 1, 0)  # 魚 1、果実 1
    assert s.to_move == 1  # 能力の無い鳥なので手番が終わる


def test_gain_food_extra_die_is_optional() -> None:
    # R p.7: 札を捨てて餌を足すのは任意
    me = board(forest=[PlacedBird(WARBLER)], hand=(WARBLER,))
    s = RULES.apply(state_of(me, board()), GainFood())
    s = RULES.apply(s, TakeDie(0, Food.FISH))
    s = RULES.apply(s, Decline())
    assert s.players[0].hand == (WARBLER,) and s.to_move == 1


def test_two_faced_die_gives_one_token_of_either_kind() -> None:
    # R p.7: 虫 / 種のダイスは、どちらか 1 個(2 個ではない)
    me = board()
    s = state_of(me, board(), feeder=("invertebrate_or_seed", "fish"))
    moves = [m for m in RULES.legal_moves(RULES.apply(s, GainFood())) if isinstance(m, TakeDie)]
    foods = {m.food for m in moves if m.index == 0}
    assert foods == {Food.INVERTEBRATE, Food.SEED}


def test_reroll_only_when_all_dice_show_the_same_face() -> None:
    # R p.7: 餌箱の残りがすべて同じ目(1 個だけの場合を含む)なら、先に振り直してよい
    me = board()
    same = RULES.apply(state_of(me, board(), feeder=("seed", "seed")), GainFood())
    assert Reroll() in RULES.legal_moves(same)
    one = RULES.apply(state_of(me, board(), feeder=("fish",)), GainFood())
    assert Reroll() in RULES.legal_moves(one)
    mixed = RULES.apply(state_of(me, board(), feeder=("seed", "fish")), GainFood())
    assert Reroll() not in RULES.legal_moves(mixed)


def test_empty_feeder_is_refilled_with_five_dice() -> None:
    # R p.7: 餌箱が空になったら 5 個とも振り直す
    s = state_of(board(), board(), feeder=("fish",))
    s = RULES.apply(RULES.apply(s, GainFood()), TakeDie(0, Food.FISH))
    assert len(s.feeder) == 5


def test_lay_eggs_respects_limit_and_loses_the_excess() -> None:
    # R p.8: 卵はどの行の鳥にも置ける(組み合わせは自由)。鳥ごとの上限まで。置けない分は失う
    forest_only = RULES.apply(state_of(board(forest=[PlacedBird(WARBLER)]), board()), LayEggs())
    assert LayEgg(Placement(F, 0)) in RULES.legal_moves(
        forest_only
    )  # 草原の行動でも森林の鳥に置ける
    # 鳥が 1 羽もいなければ、置く先が無く、卵は失われて手番が終わる
    nothing = RULES.apply(state_of(board(), board()), LayEggs())
    assert nothing.to_move == 1 and not nothing.queue
    # 上限 1 の鳥(ハシグロアビ)は 1 個だけ置ける
    loon = board(grass=[PlacedBird("ハシグロアビ")])
    s = RULES.apply(state_of(loon, board()), LayEggs())
    assert LayEgg(Placement(G, 0)) in RULES.legal_moves(s)
    s = RULES.apply(s, LayEgg(Placement(G, 0)))
    assert s.players[0].birds()[0].eggs == 1
    assert not [m for m in RULES.legal_moves(s) if isinstance(m, LayEgg)]  # 上限に達した


def test_lay_eggs_food_bonus_in_second_column() -> None:
    # R p.8: 2 列目(鳥 1 羽)は卵 2 個 + 餌 1 個を払って卵をもう 1 個(任意)
    quail = PlacedBird(QUAIL)
    me = board(grass=[quail], food=(0, 1, 0, 0, 0))
    s = RULES.apply(state_of(me, board()), LayEggs())
    at = Placement(G, 0)
    s = RULES.apply(RULES.apply(s, LayEgg(at)), LayEgg(at))
    s = RULES.apply(s, Decline())  # 餌を払わない
    mine = s.players[0]
    # ウズラの能力(起動時: 自分へ卵 1 個)で +1
    assert mine.birds()[0].eggs == 3 and mine.count(Food.SEED) == 1


def test_draw_cards_refill_tray_at_end_of_turn() -> None:
    # R p.9: 引いた表向きの札はすぐには補充せず、手番の終わりに補充する
    s = state_of(board(), board(), tray=("ミサゴ", "イスカ", "ヤブガラ"))
    s = RULES.apply(s, DrawCards())
    s = RULES.apply(s, TakeTray(0))
    assert s.players[0].hand == ("ミサゴ",)
    assert s.tray[1:] == ("イスカ", "ヤブガラ") and s.tray[0] == WARBLER  # 手番が終わって補充された
    assert s.to_move == 1


def test_pink_power_triggers_on_opponent_wetland_play_once() -> None:
    # R p.10: 桃色は、他のプレイヤーの行動で起き、次の自分の手番までに 1 回だけ
    s = state_of(board(), board(wet=[PlacedBird(KINGFISHER)]))
    s = trigger_pink(s, TABLE, 0, kind="on_opponent_play_habitat_gain_supply", habitat=W)
    assert s.players[1].count(Food.FISH) == 1
    s = trigger_pink(s, TABLE, 0, kind="on_opponent_play_habitat_gain_supply", habitat=W)
    assert s.players[1].count(Food.FISH) == 1  # 使い済み
    # 森林の鳥のプレイでは起きない
    fresh = state_of(board(), board(wet=[PlacedBird(KINGFISHER)]))
    fresh = trigger_pink(fresh, TABLE, 0, kind="on_opponent_play_habitat_gain_supply", habitat=F)
    assert fresh.players[1].count(Food.FISH) == 0


def test_pink_power_resets_at_owners_next_turn() -> None:
    # R p.10: 持ち主の次の手番の前に使い済みが戻り、また使える
    me = board(wet=[PlacedBird(KINGFISHER)], cubes=5)
    opp = board(forest=[PlacedBird(WARBLER, eggs=1)], food=(2, 0, 0, 0, 0), hand=(WARBLER,))
    s = state_of(opp, me)
    s = trigger_pink(s, TABLE, 0, kind="on_opponent_play_habitat_gain_supply", habitat=W)
    assert s.players[1].birds()[0].used
    s = RULES.apply(s, [m for m in RULES.legal_moves(s) if isinstance(m, PlayBird)][0])
    assert s.to_move == 1 and not s.players[1].birds()[0].used  # 持ち主の手番が始まる前に戻る


def test_round_end_scores_goal_resets_cubes_and_rotates_first_player() -> None:
    # R p.5: ラウンドの終わりに、目的の採点 → トレイの入れ替え → 先手を左隣へ。ラウンド 2 は 7 手番
    tile = all_goal_tiles()[0]  # 森林の鳥の数
    me = board(forest=[PlacedBird(WARBLER), PlacedBird(WARBLER)], cubes=1)
    opp = board(forest=[PlacedBird(WARBLER)], cubes=0)
    s = state_of(me, opp, goals=(tile, *all_goal_tiles()[1:4]), tray=("ミサゴ", "", ""))
    s = RULES.apply(s, [m for m in RULES.legal_moves(s) if isinstance(m, GainFood)][0])
    # 餌のダイスを 1 個取って(2 羽 → 3 列目の枠で餌 2 個)手番を終える
    while s.queue:
        s = RULES.apply(s, RULES.legal_moves(s)[0])
    assert s.round_index == 1
    assert s.players[0].goal_points == (4,) and s.players[1].goal_points == (
        1,
    )  # 1 位 4 点、2 位 1 点
    assert s.players[0].cubes == 7 and s.players[1].cubes == 7
    assert s.first_player == 1 and s.to_move == 1
    assert all(s.tray) and "ミサゴ" in s.discard  # トレイを捨てて入れ替えた


def test_game_ends_after_round_four() -> None:
    last = replace(
        state_of(board(cubes=1), board(cubes=0)), round_index=3, tray=(WARBLER, WARBLER, WARBLER)
    )
    s = RULES.apply(last, DrawCards())
    s = RULES.apply(s, TakeTray(0))
    assert RULES.is_terminal(s) and s.round_index == 4
    assert RULES.outcome(s) in ("win", "lose", "draw")
