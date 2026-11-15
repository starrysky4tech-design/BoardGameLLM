"""状態を更新する補助(山札、ダイス、卵、餌)。どれも新しい状態を返し、元の状態は変えない。

乱数は `state.seed` から作る `random.Random` で引き、使ったら種を進める。
"""

import random
from dataclasses import replace

from bglm.plugins.wingspan.logic.cards import CardTable
from bglm.plugins.wingspan.logic.models import (
    FEEDER_DICE_FACES,
    Food,
    PlacedBird,
    Placement,
)
from bglm.plugins.wingspan.logic.state import WingspanState


def next_rng(state: WingspanState) -> tuple[WingspanState, random.Random]:
    """乱数を 1 つ借りる。返す状態では種が進んでいる。"""
    return replace(state, seed=state.seed + 1), random.Random(state.seed)


def roll_feeder(state: WingspanState, count: int = 5) -> WingspanState:
    """ダイスを振って餌箱に入れる(全部振り直すときは 5。R p.7)。目は昇順に並べる。"""
    state, rng = next_rng(state)
    faces = sorted(rng.choice(FEEDER_DICE_FACES) for _ in range(count))
    return replace(state, feeder=tuple(faces))


def take_die(state: WingspanState, index: int) -> WingspanState:
    """餌箱のダイスを 1 個取り除く。空になったら 5 個とも振り直す(R p.7)。"""
    feeder = state.feeder[:index] + state.feeder[index + 1 :]
    state = replace(state, feeder=feeder)
    return roll_feeder(state) if not feeder else state


def draw_from_deck(state: WingspanState, player: int, count: int) -> WingspanState:
    """山札から count 枚を手札へ。尽きたら捨て札を混ぜ直す(R p.9)。それでも無ければ引けた分だけ。"""
    for _ in range(count):
        if not state.deck:
            if not state.discard:
                break
            state, rng = next_rng(state)
            pile = list(state.discard)
            rng.shuffle(pile)
            state = replace(state, deck=tuple(pile), discard=())
        card, rest = state.deck[0], state.deck[1:]
        board = state.players[player]
        state = replace(state, deck=rest).with_player(
            player, replace(board, hand=board.hand + (card,))
        )
    return state


def pop_deck(state: WingspanState, count: int) -> tuple[WingspanState, tuple[str, ...]]:
    """山札の上から count 枚を取り出す(手札に入れない。差し込みなどに使う)。"""
    taken: list[str] = []
    for _ in range(count):
        if not state.deck:
            if not state.discard:
                break
            state, rng = next_rng(state)
            pile = list(state.discard)
            rng.shuffle(pile)
            state = replace(state, deck=tuple(pile), discard=())
        taken.append(state.deck[0])
        state = replace(state, deck=state.deck[1:])
    return state, tuple(taken)


def egg_room(state: WingspanState, table: CardTable, player: int, at: Placement) -> int:
    bird = state.players[player].bird_at(at)
    return table.bird(bird.name).egg_limit - bird.eggs


def eggable(state: WingspanState, table: CardTable, player: int) -> list[Placement]:
    """卵を置ける鳥の位置。"""
    board = state.players[player]
    return [p for p in board.placements() if egg_room(state, table, player, p) > 0]


def add_to_bird(
    state: WingspanState,
    player: int,
    at: Placement,
    *,
    eggs: int = 0,
    cached: int = 0,
    tucked: int = 0,
) -> WingspanState:
    board = state.players[player]
    bird = board.bird_at(at)
    new = PlacedBird(
        bird.name, bird.eggs + eggs, bird.cached + cached, bird.tucked + tucked, bird.used
    )
    return state.with_player(player, board.with_bird(at, new))


def gain_food(state: WingspanState, player: int, food: Food, count: int = 1) -> WingspanState:
    return state.with_player(player, state.players[player].with_food(food, count))


def remove_card(hand: tuple[str, ...], card: str) -> tuple[str, ...]:
    """手札から 1 枚だけ取り除く(同じ札が複数あっても 1 枚)。"""
    i = hand.index(card)
    return hand[:i] + hand[i + 1 :]


def discard_card(state: WingspanState, player: int, card: str) -> WingspanState:
    board = state.players[player]
    state = state.with_player(player, replace(board, hand=remove_card(board.hand, card)))
    return replace(state, discard=state.discard + (card,))
