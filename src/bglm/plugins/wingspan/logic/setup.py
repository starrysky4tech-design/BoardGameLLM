"""ゲームの準備(出典: ルールブック R p.2)。自己対戦と、再開のときの状態づくりに使う。

実機の追跡では、山札の並びは分からない(空のまま)。自己対戦では、札の表の鳥を並べた山札を作る(試験用の山札)。
"""

import random

from bglm.plugins.wingspan.logic.board import (
    FEEDER_DICE,
    INITIAL_BIRD_CARDS,
    INITIAL_BONUS_CARDS,
    TRAY_SIZE,
    TURNS_PER_ROUND,
)
from bglm.plugins.wingspan.logic.cards import CardTable
from bglm.plugins.wingspan.logic.goals import GoalMode, all_goal_tiles
from bglm.plugins.wingspan.logic.helpers import roll_feeder
from bglm.plugins.wingspan.logic.models import PlayerBoard
from bglm.plugins.wingspan.logic.state import SetupTask, WingspanState

TEST_BONUS_DECK = ("草原管理者",)  # 表にあるボーナス。試験用に重複して使う


def initial_state(
    table: CardTable,
    seed: int,
    players: int = 2,
    *,
    copies: int = 6,
    bonus_names: tuple[str, ...] = TEST_BONUS_DECK,
    goal_mode: GoalMode = GoalMode.MAJORITY,
) -> WingspanState:
    """試験用の準備。山札は表の鳥を copies 枚ずつ混ぜたもの(実際の 170 枚の並びではない)。"""
    rng = random.Random(seed)
    deck = [name for name in sorted(table.birds) for _ in range(copies)]
    rng.shuffle(deck)
    boards: list[PlayerBoard] = []
    for _ in range(players):
        hand = tuple(deck[:INITIAL_BIRD_CARDS])
        deck = deck[INITIAL_BIRD_CARDS:]
        bonus = tuple(rng.choice(bonus_names) for _ in range(INITIAL_BONUS_CARDS))
        boards.append(
            PlayerBoard(hand=hand, bonus=bonus, food=(1, 1, 1, 1, 1), cubes=TURNS_PER_ROUND[0])
        )
    tray = tuple(deck[:TRAY_SIZE])
    deck = deck[TRAY_SIZE:]
    tiles = list(all_goal_tiles())
    rng.shuffle(tiles)
    first = rng.randrange(players)
    state = WingspanState(
        players=tuple(boards),
        to_move=0,
        first_player=first,
        round_index=0,
        feeder=(),
        tray=tray,
        deck=tuple(deck),
        discard=(),
        goals=tuple(tiles[:4]),
        goal_mode=goal_mode,
        queue=(SetupTask(),),
        pending_setup=tuple(range(players)),
        seed=seed * 1000 + 1,
    )
    return roll_feeder(state, FEEDER_DICE)
