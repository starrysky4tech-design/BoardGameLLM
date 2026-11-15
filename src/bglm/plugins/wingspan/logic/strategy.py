"""手の選択。各手を打った後、その手番の残りを貪欲に進めた局面を評価し、標本の平均が最も高い手を選ぶ。

- 探索木は作らない(02_DESIGN.md 論点 3)。手番の途中の決定は、1 手先の評価で貪欲に決める
- 山札と乱数は `belief.determinize` で標本にして、真の山札を覗かない
- 乱数は `random.Random` を引数で受ける(時間に依らず、固定シードで再現できる)
"""

import random
from dataclasses import dataclass

from bglm.core.models import TimeBudget
from bglm.plugins.wingspan.logic.belief import determinize
from bglm.plugins.wingspan.logic.evaluation import DEFAULT_WEIGHTS, Weights, evaluate
from bglm.plugins.wingspan.logic.rules import WingspanRules
from bglm.plugins.wingspan.logic.state import Move, WingspanState


@dataclass
class WingspanStrategy:
    rng: random.Random
    rules: WingspanRules
    samples: int = 3  # 標本の数(山札と乱数)
    weights: Weights = DEFAULT_WEIGHTS

    def choose(self, state: WingspanState, legal: list[Move], budget: TimeBudget) -> Move:
        if len(legal) == 1:
            return legal[0]
        me = state.to_move
        best, best_value = legal[0], float("-inf")
        worlds = [determinize(state, self.rng) for _ in range(self.samples)]
        for move in legal:
            total = 0.0
            for world in worlds:
                total += self._after_turn(self.rules.apply(world, move), me)
            value = total / len(worlds)
            if value > best_value:
                best, best_value = move, value
            if budget.expired():
                break
        return best

    def _after_turn(self, state: WingspanState, me: int) -> float:
        """手番の残りを、1 手先の評価で貪欲に進めた局面の評価値。"""
        steps = 0
        while state.queue and not state.terminal and state.to_move == me and steps < 30:
            options = self.rules.legal_moves(state)
            if not options:
                break
            if len(options) == 1:
                state = self.rules.apply(state, options[0])
            else:
                state = max(
                    (self.rules.apply(state, m) for m in options),
                    key=lambda s: evaluate(s, self.rules, me, self.weights),
                )
            steps += 1
        return evaluate(state, self.rules, me, self.weights)


def strategy_policy(seed: int, samples: int = 3):  # type: ignore[no-untyped-def]
    """自己対戦用の方針(simulation.Policy)にする。"""
    strategy = WingspanStrategy(random.Random(seed), WingspanRules(), samples=samples)
    unlimited = TimeBudget(1e9)

    def choose(state: WingspanState, legal: list[Move], rules: WingspanRules) -> Move:
        return strategy.choose(state, legal, unlimited)

    return choose
