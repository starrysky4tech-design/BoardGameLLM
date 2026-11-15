"""自己プレイのテスト: 固定シードで再現でき、不正な手が出ず、完走する。"""

import random
from dataclasses import replace

from bglm.plugins.maquis.logic.simulation import play_game, random_policy, strategy_policy
from bglm.plugins.maquis.logic.strategy import MaquisStrategy, load_weights


def test_random_play_is_reproducible_and_finishes() -> None:
    a = play_game(random_policy(random.Random(1)), random.Random(2))
    b = play_game(random_policy(random.Random(1)), random.Random(2))
    assert a == b
    assert a.moves > 0


def test_many_random_games_never_make_an_illegal_move() -> None:
    for seed in range(30):
        result = play_game(random_policy(random.Random(seed)), random.Random(100 + seed))
        assert result.turns <= 11


def test_strategy_game_finishes_without_illegal_moves() -> None:
    weights = replace(load_weights(), samples=5)
    policy = strategy_policy(MaquisStrategy(weights=weights, rng=random.Random(0)))
    result = play_game(policy, random.Random(3), max_turns=4)
    assert result.turns <= 4
