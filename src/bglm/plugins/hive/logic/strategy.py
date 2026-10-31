"""Hive の思考。反復深化のアルファベータで1手を選ぶ(docs/02 の「Hiveの手の選択」)。

画面にも VLM にも依存しない。乱数は random.Random を引数で受ける(グローバル乱数は使わない)。
"""

import random
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from bglm.core.models import TimeBudget
from bglm.plugins.hive.logic.models import Color, HiveMove, HiveState, opponent
from bglm.plugins.hive.logic.rules import HiveRules

WEIGHTS_PATH = Path(__file__).resolve().parents[1] / "data" / "strategy.toml"
WIN_SCORE = 1_000_000.0  # 囲んで勝つ/囲まれて負ける局面の評価
DEFAULT_MAX_DEPTH = 4


@dataclass(frozen=True)
class Weights:
    queen_pressure: float  # 相手の女王の周囲の埋まり数 - 自分の女王の周囲の埋まり数


def load_weights(path: Path = WEIGHTS_PATH) -> Weights:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return Weights(queen_pressure=float(data["queen_pressure"]))


class OutOfTimeError(Exception):
    """思考時間が尽きた。その時点までに完了した深さの結果を使う。"""


class HiveStrategy:
    def __init__(
        self,
        rules: HiveRules | None = None,
        weights: Weights | None = None,
        rng: random.Random | None = None,
        max_depth: int = DEFAULT_MAX_DEPTH,
    ) -> None:
        self._rules = rules or HiveRules()
        self._weights = weights or load_weights()
        self._rng = rng or random.Random(0)
        self._max_depth = max_depth

    def choose(self, state: HiveState, legal: Sequence[HiveMove], budget: TimeBudget) -> HiveMove:
        if not legal:
            raise ValueError("合法手が無い(Pass も含めて1つは必ずあるはず)")
        order = list(legal)
        self._rng.shuffle(order)  # 同点の手は乱数の順で選ばれる
        chosen = order[0]
        for depth in range(1, self._max_depth + 1):
            try:
                chosen = self._search_root(state, order, depth, budget)
            except OutOfTimeError:
                break
            if budget.expired():
                break
        return chosen

    def _search_root(
        self, state: HiveState, moves: Sequence[HiveMove], depth: int, budget: TimeBudget
    ) -> HiveMove:
        best_move = moves[0]
        best = float("-inf")
        alpha = float("-inf")
        for move in moves:
            child = self._rules.apply(state, move)
            value = -self._negamax(child, depth - 1, float("-inf"), -alpha, budget)
            if value > best:
                best, best_move = value, move
            alpha = max(alpha, best)
        return best_move

    def _negamax(
        self, state: HiveState, depth: int, alpha: float, beta: float, budget: TimeBudget
    ) -> float:
        """評価は手番の側から見た値。"""
        if budget.expired():
            raise OutOfTimeError
        if self._rules.is_terminal(state):
            return self._terminal_score(state)
        if depth == 0:
            return self._evaluate(state)
        value = float("-inf")
        for child in self._ordered_children(state):
            value = max(value, -self._negamax(child, depth - 1, -beta, -alpha, budget))
            alpha = max(alpha, value)
            if alpha >= beta:
                break
        return value

    def _ordered_children(self, state: HiveState) -> list[HiveState]:
        """子の局面を、相手にとって悪い順(評価の良い手番側の値の小さい順)に並べる。枝刈りを効かせるため。"""
        children = [self._rules.apply(state, move) for move in self._rules.legal_moves(state)]
        children.sort(key=self._evaluate)
        return children

    def _terminal_score(self, state: HiveState) -> float:
        match self._rules.outcome(state):
            case "win":
                return WIN_SCORE
            case "lose":
                return -WIN_SCORE
            case _:
                return 0.0

    def _evaluate(self, state: HiveState) -> float:
        """手番の側から見た評価。合法手は作らない(葉で両者の合法手を作ると、探索が遅すぎるため)。

        女王の周りの埋まり: 相手の女王が囲まれるほど良く、自分の女王が囲まれるほど悪い。
        """
        me = state.to_move
        them = opponent(me)
        w = self._weights
        pressure = _queen_neighbours(state, them) - _queen_neighbours(state, me)
        return w.queen_pressure * pressure


def _queen_neighbours(state: HiveState, color: Color) -> int:
    at = state.queen_at(color)
    if at is None:
        return 0
    return sum(1 for n in at.neighbors() if n in state.stacks)
