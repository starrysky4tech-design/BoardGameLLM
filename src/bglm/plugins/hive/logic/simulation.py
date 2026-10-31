"""両者の思考だけで1ゲームを完走させる自己対戦。画面なし。

ルールの矛盾と、不正な手が出ないことを見つける。思考は探索の深さだけで決め、時間には依らない。
"""

import random
from dataclasses import dataclass

from bglm.core.models import TimeBudget
from bglm.plugins.hive.logic.models import Color, HiveState, initial_state
from bglm.plugins.hive.logic.rules import HiveRules, hive_connected
from bglm.plugins.hive.logic.strategy import HiveStrategy

_UNLIMITED = TimeBudget(1e9)


@dataclass(frozen=True)
class GameResult:
    outcome: (
        str | None
    )  # 終了した場合は HiveRules.outcome の値(手番の側から見た値)。途中で打ち切ったら None
    turns: int  # 手番の数(パスを含む)
    final: HiveState


def play_game(seed: int, max_turns: int = 200, max_depth: int = 2) -> GameResult:
    rules = HiveRules()
    players = {
        Color.WHITE: HiveStrategy(rng=random.Random(seed * 2), max_depth=max_depth),
        Color.BLACK: HiveStrategy(rng=random.Random(seed * 2 + 1), max_depth=max_depth),
    }
    state = initial_state()
    while state.turn < max_turns and not rules.is_terminal(state):
        legal = rules.legal_moves(state)
        move = players[state.to_move].choose(state, legal, _UNLIMITED)
        if move not in legal:
            raise AssertionError(f"合法手でない手: turn={state.turn} move={move}")
        state = rules.apply(state, move)
        if not hive_connected(state.occupied()):
            raise AssertionError(f"ハイブが割れた: turn={state.turn}")
    outcome = rules.outcome(state) if rules.is_terminal(state) else None
    return GameResult(outcome=outcome, turns=state.turn, final=state)
