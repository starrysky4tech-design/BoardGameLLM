"""両者の方針だけで 1 ゲームを完走させる自己対戦。画面なし。

ルールの矛盾と、不正な手が出ないことを見つける。毎手のあとに不変条件を検査する:
- 札の総数が変わらない(山札 + 捨て札 + トレイ + 手札 + 盤の鳥 + 差し込んだ札)
- 鳥は 1 行 5 羽まで、卵は上限まで、餌は 0 以上
- 終わっていないのに合法手が 0 になる行き詰まりが無い
"""

import random
from collections.abc import Callable
from dataclasses import dataclass

from bglm.plugins.wingspan.logic.board import MAX_BIRDS_PER_ROW
from bglm.plugins.wingspan.logic.cards import CardTable, default_table
from bglm.plugins.wingspan.logic.rules import WingspanRules
from bglm.plugins.wingspan.logic.scoring import ScoreBreakdown
from bglm.plugins.wingspan.logic.setup import initial_state
from bglm.plugins.wingspan.logic.state import Move, WingspanState

Policy = Callable[[WingspanState, list[Move], WingspanRules], Move]


def random_policy(rng: random.Random) -> Policy:
    """合法手から無作為に選ぶ。"""

    def choose(state: WingspanState, legal: list[Move], rules: WingspanRules) -> Move:
        return rng.choice(legal)

    return choose


def total_cards(state: WingspanState) -> int:
    placed = sum(len(b.birds()) + sum(x.tucked for x in b.birds()) for b in state.players)
    hands = sum(len(b.hand) for b in state.players)
    return len(state.deck) + len(state.discard) + sum(1 for c in state.tray if c) + hands + placed


def check_invariants(state: WingspanState, table: CardTable, expected_cards: int) -> None:
    got = total_cards(state)
    if got != expected_cards:
        raise AssertionError(f"札の総数が変わった: {got} != {expected_cards}")
    for p, board in enumerate(state.players):
        if any(n < 0 for n in board.food):
            raise AssertionError(f"餌が負: player={p} {board.food}")
        if board.cubes < 0:
            raise AssertionError(f"キューブが負: player={p}")
        for habitat_row in board.rows:
            if len(habitat_row) > MAX_BIRDS_PER_ROW:
                raise AssertionError(f"1 行に 5 羽を超えた: player={p}")
        for bird in board.birds():
            limit = table.bird(bird.name).egg_limit
            if not 0 <= bird.eggs <= limit:
                raise AssertionError(f"卵が範囲外: {bird.name} {bird.eggs}/{limit}")
    if len(state.feeder) > 5:
        raise AssertionError("餌箱のダイスが 5 個を超えた")


@dataclass(frozen=True)
class GameResult:
    outcomes: tuple[str | None, ...]  # プレイヤーごとの勝敗(視点を替えて求める)
    scores: tuple[ScoreBreakdown, ...]
    steps: int  # 手の数(決定を含む)
    final: WingspanState


def play_game(
    seed: int,
    policies: tuple[Policy, ...] | None = None,
    *,
    players: int = 2,
    max_steps: int = 5000,
    check: bool = True,
) -> GameResult:
    table = default_table()
    rules = WingspanRules(table)
    if policies is None:
        policies = tuple(random_policy(random.Random(seed * 10 + i)) for i in range(players))
    state = initial_state(table, seed, players)
    expected = total_cards(state)
    steps = 0
    while not rules.is_terminal(state):
        if steps >= max_steps:
            raise AssertionError(f"手の数が上限を超えた(無限ループの疑い): seed={seed}")
        legal = rules.legal_moves(state)
        if not legal:
            raise AssertionError(f"合法手が無い: seed={seed} step={steps} queue={state.queue}")
        move = policies[state.to_move](state, legal, rules)
        if move not in legal:
            raise AssertionError(f"合法手でない手: {move}")
        state = rules.apply(state, move)
        steps += 1
        if check:
            check_invariants(state, table, expected)
    outcomes = tuple(WingspanRules(table, me=i).outcome(state) for i in range(players))
    return GameResult(outcomes, rules.scores(state), steps, state)
