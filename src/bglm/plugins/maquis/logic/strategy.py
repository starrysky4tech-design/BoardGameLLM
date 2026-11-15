"""Maquis の思考。配置はモンテカルロ、行動は貪欲(docs/02 の「Maquis の判断」)。

画面にも VLM にも依存しない。乱数は random.Random を引数で受ける。

- **最優先の制約**: 全団員が帰還できない配置を避ける(全員捕縛は即敗北)。配置のたびに巡回が1枚出るので、
  山札の残りを無作為に並べ(標本)、残りの配置を簡単な方針で打ち切って、そのターンの終了時の評価を平均する。
  標本は候補の手の間で共通にして、差のばらつきを減らす
- 行動フェイズ: 評価が最も上がる行動(`Resolve`)を貪欲に選び、上がる行動が無ければ終了する
- 評価は、確認済みの範囲(資材、★、使える団員)だけで作る。任務の勝ち筋は未確認(`data/strategy.toml`)
"""

import random
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from bglm.core.models import TimeBudget
from bglm.plugins.maquis.logic.models import (
    EndPhase,
    MaquisMove,
    MaquisState,
    Place,
    Resolve,
)
from bglm.plugins.maquis.logic.patrol import PatrolCard, load_cards
from bglm.plugins.maquis.logic.rules import Action, MaquisRules, load_actions

WEIGHTS_PATH = Path(__file__).resolve().parents[1] / "data" / "strategy.toml"
RESOURCE_NAMES = ("food", "medicine", "funds", "intel", "guns", "explosives", "morale")


@dataclass(frozen=True)
class Weights:
    resource: dict[str, float]
    agent: float
    star: float
    defeat: float
    blocked_card: float
    samples: int


def load_weights(path: Path = WEIGHTS_PATH) -> Weights:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    resource = {name: float(data["resource"][name]) for name in RESOURCE_NAMES}
    return Weights(
        resource=resource,
        agent=float(data["agent"]),
        star=float(data["star"]),
        defeat=float(data["defeat"]),
        blocked_card=float(data["blocked_card"]),
        samples=int(data["samples"]),
    )


class MaquisStrategy:
    def __init__(
        self,
        rules: MaquisRules | None = None,
        weights: Weights | None = None,
        rng: random.Random | None = None,
        actions: dict[str, tuple[Action, ...]] | None = None,
    ) -> None:
        self._rules = rules or MaquisRules()
        self._weights = weights or load_weights()
        self._rng = rng or random.Random(0)
        self._actions = actions if actions is not None else load_actions()
        self._cards = load_cards()

    # --- 入口 ---

    def choose(
        self, state: MaquisState, legal: Sequence[MaquisMove], budget: TimeBudget
    ) -> MaquisMove:
        if not legal:
            raise ValueError("合法手が無い")
        if len(legal) == 1:
            return legal[0]
        places = [m for m in legal if isinstance(m, Place)]
        if places:
            return self._choose_placement(state, places, budget)
        return self._choose_action(state, legal)

    # --- 行動フェイズ ---

    def _choose_action(self, state: MaquisState, legal: Sequence[MaquisMove]) -> MaquisMove:
        """評価が最も上がる行動。上がるものが無ければ終了(確認ダイアログが出うる行動の残りは捨てる)。"""
        best: MaquisMove = EndPhase()
        best_gain = 0.0
        base = self._score(state)
        for move in legal:
            if not isinstance(move, Resolve):
                continue
            gain = self._score(self._rules.apply(state, move)) - base
            if gain > best_gain:
                best, best_gain = move, gain
        return best

    # --- 配置フェイズ(モンテカルロ) ---

    def _choose_placement(
        self, state: MaquisState, places: Sequence[Place], budget: TimeBudget
    ) -> MaquisMove:
        totals = {p: 0.0 for p in places}
        done = 0
        for _ in range(self._weights.samples):
            if done >= 1 and budget.expired():
                break
            draws = self._sample_draws(state)
            for place in places:
                totals[place] += self._rollout(state, place, draws)
            done += 1
        # 同点は乱数の順(先に混ぜる)
        order = list(places)
        self._rng.shuffle(order)
        return max(order, key=lambda p: totals[p])

    def _sample_draws(self, state: MaquisState) -> list[PatrolCard]:
        """これから引かれるカードの並びの標本。山札の残りを混ぜ、尽きたら全10枚を混ぜ直して続ける。"""
        rest = [card for card, n in state.deck.remaining for _ in range(n)]
        self._rng.shuffle(rest)
        again = list(self._cards)
        self._rng.shuffle(again)
        return rest + again

    def _rollout(self, state: MaquisState, first: Place, draws: list[PatrolCard]) -> float:
        """`first` を置き、残りの配置を簡単な方針で打ち、そのターンの終了時の評価を返す。"""
        current = state
        move: MaquisMove = first
        used = 0
        blocked = 0
        while True:
            current = self._rules.apply(current, move)
            try:
                current = self._rules.place_patrol(current, draws[used])
            except ValueError:
                blocked += 1  # 3地点とも埋まったカード(扱いは未確認)。山札は進める
            used += 1
            if current.unplaced <= 0:
                break
            move = self._placement_policy(current)
        return self._finish_turn(current) - blocked * self._weights.blocked_card

    def _placement_policy(self, state: MaquisState) -> MaquisMove:
        """打ち切りの方針: 置ける地点のうち、1回の行動の価値が最も高いところ(同点は乱数)。"""
        options = [m for m in self._rules.legal_moves(state) if isinstance(m, Place)]
        self._rng.shuffle(options)
        return max(options, key=lambda p: self._location_value(p.location, state.recruits_left))

    def _location_value(self, location: str, recruits_left: int) -> float:
        best = 0.0
        for action in self._actions.get(location, ()):
            if action.recruit > recruits_left:
                continue  # 勧誘できる人がもういない
            value = self._action_value(action)
            best = max(best, value)
        return best

    def _action_value(self, action: Action) -> float:
        w = self._weights
        value = sum(w.resource[n] * v for n, v in action.gain.items())
        value -= sum(w.resource[n] * v for n, v in action.cost.items())
        return value + w.agent * action.recruit + w.star * action.star

    def _finish_turn(self, state: MaquisState) -> float:
        """配置が終わった状態から、行動(貪欲)とターン終了までを進めた評価。"""
        current = self._rules.apply(state, EndPhase())  # 行動フェイズへ
        for _ in range(len(current.agents) + 1):
            move = self._choose_action(current, self._rules.legal_moves(current))
            if isinstance(move, EndPhase):
                break
            current = self._rules.apply(current, move)
        return self._score(self._rules.apply(current, EndPhase()))

    # --- 評価 ---

    def _score(self, state: MaquisState) -> float:
        w = self._weights
        if state.defeated:
            return -w.defeat
        resources = sum(w.resource[n] * state.resources.get(n) for n in RESOURCE_NAMES)
        stars = w.star * sum(state.stars)
        # 行動フェイズでは、地図に残る団員は(帰還できなければ)ターン終了で捕縛される。評価はターン終了後に行う
        return resources + stars + w.agent * state.agents_total


__all__ = ["MaquisStrategy", "Weights", "load_weights"]
