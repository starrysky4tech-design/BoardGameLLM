"""Hive の思考。反復深化のアルファベータで1手を選ぶ(docs/02 の「Hiveの手の選択」)。

画面にも VLM にも依存しない。乱数は random.Random を引数で受ける(グローバル乱数は使わない)。
"""

import random
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from bglm.core.models import TimeBudget
from bglm.plugins.hive.logic.models import Color, HiveMove, HiveState, Kind, Move, Place, opponent
from bglm.plugins.hive.logic.rules import HiveRules

WEIGHTS_PATH = Path(__file__).resolve().parents[1] / "data" / "strategy.toml"
WIN_SCORE = 1_000_000.0  # 囲んで勝つ/囲まれて負ける局面の評価
DEFAULT_MAX_DEPTH = 4


@dataclass(frozen=True)
class Weights:
    queen_pressure: float  # 相手の女王の周囲の埋まり数 - 自分の女王の周囲の埋まり数
    mobility: float  # 動ける手の数の差
    queen_mobility: float  # 女王が動ける手の数の差


def load_weights(path: Path = WEIGHTS_PATH) -> Weights:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return Weights(
        queen_pressure=float(data["queen_pressure"]),
        mobility=float(data["mobility"]),
        queen_mobility=float(data["queen_mobility"]),
    )


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
        for move in self._rules.legal_moves(state):
            child = self._rules.apply(state, move)
            value = max(value, -self._negamax(child, depth - 1, -beta, -alpha, budget))
            alpha = max(alpha, value)
            if alpha >= beta:
                break
        return value

    def _terminal_score(self, state: HiveState) -> float:
        match self._rules.outcome(state):
            case "win":
                return WIN_SCORE
            case "lose":
                return -WIN_SCORE
            case _:
                return 0.0

    def _evaluate(self, state: HiveState) -> float:
        me = state.to_move
        them = opponent(me)
        w = self._weights
        pressure = _queen_neighbours(state, them) - _queen_neighbours(state, me)
        my_moves = self._rules.legal_moves(state)
        their_moves = self._rules.legal_moves(replace(state, to_move=them))
        queen_mobility = _queen_move_count(state, my_moves) - _queen_move_count(
            replace(state, to_move=them), their_moves
        )
        mobility = len(my_moves) - len(their_moves)
        return (
            w.queen_pressure * pressure + w.mobility * mobility + w.queen_mobility * queen_mobility
        )


def _queen_neighbours(state: HiveState, color: Color) -> int:
    at = state.queen_at(color)
    if at is None:
        return 0
    return sum(1 for n in at.neighbors() if n in state.stacks)


def _queen_move_count(state: HiveState, moves: Sequence[HiveMove]) -> int:
    count = 0
    for move in moves:
        if isinstance(move, Place) and move.kind is Kind.QUEEN:
            count += 1
        elif isinstance(move, Move):
            top = state.top(move.frm)
            if top is not None and top.kind is Kind.QUEEN:
                count += 1
    return count
