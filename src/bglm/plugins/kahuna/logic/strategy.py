"""Kahuna の思考ロジック。評価関数による1手の選択(docs/02 の「アルゴリズム設計」)。

画面にも VLM にも依存しない。盤面の状態だけを入力にする。
1回の呼び出しは「次の1手」を返し、手番の中で何度も呼ばれる。カードを使い切るか、引く/終えるを
選ぶと手番が終わる。
"""

import tomllib
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from bglm.core.models import TimeBudget
from bglm.plugins.kahuna.logic.models import (
    UNKNOWN_CARD,
    BoardDef,
    DiscardCard,
    DrawDeck,
    DrawMarket,
    KahunaMove,
    KahunaState,
    PassDraw,
    PlaceStick,
    Player,
    RemoveStick,
    default_board,
)
from bglm.plugins.kahuna.logic.rules import (
    KahunaRules,
    count_sticks,
    count_sticks_at,
    count_stones,
    place_stick,
)

WEIGHTS_PATH = Path(__file__).resolve().parents[1] / "data" / "strategy.toml"
WIN_SCORE = 1_000_000.0  # 途中終了で勝つ/負ける手の評価


@dataclass(frozen=True)
class StrategyWeights:
    stone_by_round: tuple[float, float, float] = (10.0, 14.0, 20.0)
    late_cards: int = 4
    late_multiplier: float = 2.0
    near_control: float = 3.0
    stick: float = 1.0
    card_cost: float = 0.5
    deck_card_fraction: float = 0.8
    min_gain: float = 0.2

    def __post_init__(self) -> None:
        # docs/05 の「パラメータ境界値の設計」: 範囲外は読み込み時に弾く
        if len(self.stone_by_round) != 3 or any(w < 0 for w in self.stone_by_round):
            raise ValueError(f"stone_by_round は0以上の3つ: {self.stone_by_round}")
        if self.late_cards < 0:
            raise ValueError(f"late_cards は0以上: {self.late_cards}")
        if self.late_multiplier < 1.0:
            raise ValueError(f"late_multiplier は1.0以上: {self.late_multiplier}")
        if min(self.near_control, self.stick, self.card_cost, self.min_gain) < 0:
            raise ValueError("near_control・stick・card_cost・min_gain は0以上")
        if not 0.0 <= self.deck_card_fraction <= 1.0:
            raise ValueError(f"deck_card_fraction は0.0〜1.0: {self.deck_card_fraction}")


def load_weights(path: Path = WEIGHTS_PATH) -> StrategyWeights:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    evaluation, cost = data["evaluation"], data["cost"]
    rounds = evaluation["stone_by_round"]
    return StrategyWeights(
        stone_by_round=(rounds[0], rounds[1], rounds[2]),
        late_cards=evaluation["late_cards"],
        late_multiplier=evaluation["late_multiplier"],
        near_control=evaluation["near_control"],
        stick=evaluation["stick"],
        card_cost=cost["card"],
        deck_card_fraction=cost["deck_card_fraction"],
        min_gain=cost["min_gain"],
    )


class KahunaStrategy:
    def __init__(
        self,
        board: BoardDef | None = None,
        weights: StrategyWeights | None = None,
        rules: KahunaRules | None = None,
    ) -> None:
        self.board = board or default_board()
        self.weights = weights or load_weights()
        self.rules = rules or KahunaRules(self.board)

    # --- 評価 -------------------------------------------------------------------

    def evaluate(self, state: KahunaState) -> float:
        """自分から見た盤面の良さ。大きいほど良い。"""
        if state.over:
            return {Player.ME: WIN_SCORE, Player.OPPONENT: -WIN_SCORE, None: 0.0}[state.winner]
        w = self.weights
        stone_weight = w.stone_by_round[state.round - 1]
        if state.deck_count + len(state.market) <= w.late_cards:
            stone_weight *= w.late_multiplier
        score = stone_weight * (
            count_stones(state.stones, Player.ME) - count_stones(state.stones, Player.OPPONENT)
        )
        score += w.near_control * (
            self._near_control(state, Player.ME) - self._near_control(state, Player.OPPONENT)
        )
        score += w.stick * (
            count_sticks(state.sticks, Player.ME) - count_sticks(state.sticks, Player.OPPONENT)
        )
        return score

    def _near_control(self, state: KahunaState, player: Player) -> int:
        """あと1本置けば支配できる島の数(支配済みの島と、置ける点線が無い島は除く)。"""
        count = 0
        for island in range(len(self.board.islands)):
            if state.stones[island] == player:
                continue
            mine = count_sticks_at(self.board, state.sticks, island, player)
            if 2 * mine > self.board.degree(island) or 2 * (mine + 1) <= self.board.degree(island):
                continue
            if any(state.sticks[line] is None for line in self.board.lines_of[island]):
                count += 1
        return count

    def card_value(self, state: KahunaState, card: int) -> float:
        """このカードを持ったとき、杖コマを置いて得られる評価の増分の最大値(0以上)。"""
        if card == UNKNOWN_CARD:
            return 0.0
        base = self.evaluate(state)
        best = 0.0
        for line in self.board.lines_of[card]:
            if state.sticks[line] is not None:
                continue
            sticks, stones = place_stick(self.board, state.sticks, state.stones, line, Player.ME)
            after = self.evaluate(replace(state, sticks=sticks, stones=stones))
            best = max(best, after - base)
        return best

    # --- 選択 -------------------------------------------------------------------

    def choose(
        self, state: KahunaState, legal: Sequence[KahunaMove], budget: TimeBudget
    ) -> KahunaMove:
        if not legal:
            raise ValueError("合法手が無い")
        base = self.evaluate(state)

        # 1. 杖コマを置く/除去する手のうち、カードの代価を引いても得になる最善手
        best_move: KahunaMove | None = None
        best_net = self.weights.min_gain
        for move in legal:
            if budget.expired():
                break
            if isinstance(move, PlaceStick):
                cards = 1
            elif isinstance(move, RemoveStick):
                cards = 2
            else:
                continue
            net = self.evaluate(self.rules.apply_unchecked(state, move)) - base
            net -= self.weights.card_cost * cards
            if net > best_net:
                best_move, best_net = move, net
        if best_move is not None:
            return best_move

        # 2. 手番を終える: 引く(手札が5枚なら先に捨てる)。引けなければ引かずに終える
        draw = self._best_draw(state, legal)
        if draw is not None:
            return draw
        discard = self._least_useful_discard(state, legal)
        if discard is not None and self._could_draw_after_discarding(state):
            return discard
        return next((m for m in legal if isinstance(m, PassDraw)), legal[0])

    def _best_draw(self, state: KahunaState, legal: Sequence[KahunaMove]) -> KahunaMove | None:
        best: KahunaMove | None = None
        best_value = -1.0
        for move in legal:
            if isinstance(move, DrawMarket):
                value = self.card_value(replace(state, hand=(*state.hand, move.card)), move.card)
            elif isinstance(move, DrawDeck):
                value = self._deck_value(state)
            else:
                continue
            if value > best_value:
                best, best_value = move, value
        return best

    def _deck_value(self, state: KahunaState) -> float:
        """山札の中身は分からないので、12島の札の有用さの平均で見積もる。"""
        islands = range(len(self.board.islands))
        total = sum(self.card_value(replace(state, hand=(*state.hand, c)), c) for c in islands)
        return self.weights.deck_card_fraction * total / len(self.board.islands)

    def _least_useful_discard(
        self, state: KahunaState, legal: Sequence[KahunaMove]
    ) -> KahunaMove | None:
        worst: KahunaMove | None = None
        worst_value = float("inf")
        for move in legal:
            if isinstance(move, DiscardCard):
                value = self.card_value(state, move.card)
                if value < worst_value:
                    worst, worst_value = move, value
        return worst

    @staticmethod
    def _could_draw_after_discarding(state: KahunaState) -> bool:
        """手札が5枚で引けないとき、捨てれば引ける札があるか。"""
        return state.deck_count > 0 or any(c != UNKNOWN_CARD for c in state.market)
