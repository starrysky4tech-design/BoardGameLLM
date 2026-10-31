"""Hive の思考と自己対戦の単体テスト。思考の強さは見ず、合法手を返すことと完走することを確かめる。"""

import random

from tests.plugins.hive.support.helpers import B, W, state

from bglm.core.models import TimeBudget
from bglm.plugins.hive.logic.models import Color, Kind, initial_state
from bglm.plugins.hive.logic.rules import HiveRules, hive_connected
from bglm.plugins.hive.logic.simulation import play_game
from bglm.plugins.hive.logic.strategy import HiveStrategy

RULES = HiveRules()


def test_choose_returns_a_legal_move() -> None:
    s = state([(0, 0, W, Kind.QUEEN), (1, 0, B, Kind.ANT)], turn=3)
    legal = RULES.legal_moves(s)
    move = HiveStrategy(rng=random.Random(1), max_depth=2).choose(s, legal, TimeBudget(1e9))
    assert move in legal


def test_choose_returns_pass_when_it_is_the_only_move() -> None:
    s = state(hand={(W, Kind.QUEEN): 0}, turn=0)
    legal = RULES.legal_moves(s)
    assert HiveStrategy(rng=random.Random(1)).choose(s, legal, TimeBudget(1e9)) in legal


def test_self_play_finishes_with_legal_moves_only() -> None:
    result = play_game(seed=3, max_turns=12, max_depth=1)
    assert result.turns <= 12
    assert hive_connected(result.final.occupied())


def test_initial_state_has_five_kinds_to_place() -> None:
    kinds = {k for (c, k), n in initial_state().hand.items() if c is Color.WHITE and n > 0}
    assert kinds == set(Kind)
