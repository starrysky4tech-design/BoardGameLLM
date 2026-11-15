"""Maquis の自己プレイ(固定シードで再現できる)。方針の比較と、不正な手が出ないことの確認に使う。

巡回カードは山札の残りから一様に引く(実機の山札の並びが引く順かは未確認)。ルールが未確認の部分
(任務の達成、士気の下がる条件)は含まないので、結果は「敗北せずに何ターン進めたか」と、団員・資材・★で測る。
"""

import random
from collections.abc import Callable
from dataclasses import dataclass

from bglm.core.models import TimeBudget
from bglm.plugins.maquis.logic.models import MaquisMove, MaquisState, Place
from bglm.plugins.maquis.logic.patrol import load_cards
from bglm.plugins.maquis.logic.rules import MaquisRules, initial_state
from bglm.plugins.maquis.logic.strategy import MaquisStrategy

Policy = Callable[[MaquisState, list[MaquisMove]], MaquisMove]
DEFAULT_MAX_TURNS = 11  # アプリ内ルールの「ゲームは11ターンで終了」(難易度による。普通は14)
STEP_LIMIT = 400  # 無限ループの保険


@dataclass(frozen=True)
class GameResult:
    defeated: bool
    turns: int  # 敗北したターン、または終えたターンの数
    agents: int  # 終了時の使える団員(捕縛の分は引かれる)
    stars: int
    resources: int  # 士気以外の資材の合計
    blocked: int  # 3地点とも埋まったカードが引かれた回数(扱いは未確認)
    moves: int


def random_policy(rng: random.Random) -> Policy:
    """合法手から無作為に選ぶ方針(比較の基準)。"""
    return lambda state, legal: rng.choice(legal)


def strategy_policy(strategy: MaquisStrategy, limit_sec: float = 30.0) -> Policy:
    def choose(state: MaquisState, legal: list[MaquisMove]) -> MaquisMove:
        return strategy.choose(state, legal, TimeBudget(limit_sec))

    return choose


def play_game(
    policy: Policy,
    rng: random.Random,
    rules: MaquisRules | None = None,
    max_turns: int = DEFAULT_MAX_TURNS,
) -> GameResult:
    rules = rules or MaquisRules()
    state = initial_state()
    blocked = 0
    moves = 0
    while not rules.is_terminal(state) and state.turn <= max_turns:
        if moves >= STEP_LIMIT:
            raise RuntimeError("手数の上限を超えた(終わらない)")
        legal = rules.legal_moves(state)
        move = policy(state, legal)
        if move not in legal:
            raise ValueError(f"不正な手: {move}")
        state = rules.apply(state, move)
        moves += 1
        if isinstance(move, Place):
            cards = [c for c, n in state.deck.remaining for _ in range(n)] or load_cards()
            card = rng.choice(cards)  # 山札が空なら、全10枚を混ぜ直す(実機で確認)
            try:
                state = rules.place_patrol(state, card)
            except ValueError:
                blocked += 1
    r = state.resources
    return GameResult(
        defeated=state.defeated,
        turns=min(state.turn, max_turns) if not state.defeated else state.turn - 1,
        agents=state.agents_total,
        stars=sum(state.stars),
        resources=sum(r.get(n) for n in r.__dataclass_fields__ if n != "morale"),
        blocked=blocked,
        moves=moves,
    )
