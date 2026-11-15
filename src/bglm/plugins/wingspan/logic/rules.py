"""Wingspan のルール(`Rules` の実装)。合法手、手の適用、終局と勝敗、予測との差。

画面にも VLM にも依存しない。期待値の出典はルールブック(R)と付録(A)、実機の観測(RESULT.md)。
"""

from typing import Any

from bglm.plugins.wingspan.logic.bonus import BonusCard
from bglm.plugins.wingspan.logic.cards import CardTable, default_bonus, default_table
from bglm.plugins.wingspan.logic.scoring import ScoreBreakdown, score_board, winner
from bglm.plugins.wingspan.logic.state import Move, WingspanState
from bglm.plugins.wingspan.logic.turn import apply_move, legal_moves


class WingspanRules:
    def __init__(
        self,
        table: CardTable | None = None,
        bonus: dict[str, BonusCard] | None = None,
        me: int = 0,
    ) -> None:
        self.table = table or default_table()
        self.bonus = bonus if bonus is not None else default_bonus()
        self.me = me  # outcome の視点(自分のプレイヤー番号)

    def legal_moves(self, state: WingspanState) -> list[Move]:
        return legal_moves(state, self.table)

    def apply(self, state: WingspanState, move: Move) -> WingspanState:
        """手を打った後の予測盤面。乱数は state.seed から決まるので、同じ状態と手なら同じ結果になる。"""
        return apply_move(state, self.table, move)

    def is_terminal(self, state: WingspanState) -> bool:
        return state.terminal

    def scores(self, state: WingspanState) -> tuple[ScoreBreakdown, ...]:
        return tuple(score_board(b, self.table.bird, self.bonus) for b in state.players)

    def outcome(self, state: WingspanState) -> str | None:
        """終局後の自分の勝敗。同点は残した餌の多い方、なお同点なら引き分け(R p.5)。"""
        if not state.terminal:
            return None
        totals = tuple(s.total for s in self.scores(state))
        winners = winner(state.players, totals)
        if self.me not in winners:
            return "lose"
        return "win" if len(winners) == 1 else "draw"

    def diff(self, predicted: WingspanState, actual: WingspanState) -> dict[str, Any]:
        """予測と実際の差。自分の盤だけを比べる(相手の手番は予測しない。02_DESIGN.md 論点 6)。"""
        out: dict[str, Any] = {}
        a, b = predicted.players[self.me], actual.players[self.me]
        if a.rows != b.rows:
            out["rows"] = (a.rows, b.rows)
        if a.food != b.food:
            out["food"] = (a.food, b.food)
        if len(a.hand) != len(b.hand):
            out["hand_size"] = (len(a.hand), len(b.hand))
        if a.cubes != b.cubes:
            out["cubes"] = (a.cubes, b.cubes)
        return out
