"""思考の単体テスト。方針が合法手だけを選び、無作為の方針に勝ち越すことを確かめる。"""

import random

from bglm.core.models import TimeBudget
from bglm.plugins.wingspan.logic.belief import determinize
from bglm.plugins.wingspan.logic.cards import default_table
from bglm.plugins.wingspan.logic.rules import WingspanRules
from bglm.plugins.wingspan.logic.setup import initial_state
from bglm.plugins.wingspan.logic.simulation import play_game, random_policy
from bglm.plugins.wingspan.logic.strategy import WingspanStrategy, strategy_policy


def test_determinize_keeps_the_deck_contents_but_not_the_order() -> None:
    state = initial_state(default_table(), 1)
    sample = determinize(state, random.Random(5))
    assert sorted(sample.deck) == sorted(state.deck)
    assert sample.deck != state.deck  # 並びは取り直される(先を覗き見ない)
    assert sample.players == state.players and sample.tray == state.tray


def test_strategy_returns_a_legal_move() -> None:
    rules = WingspanRules()
    state = initial_state(default_table(), 2)
    strategy = WingspanStrategy(random.Random(0), rules, samples=2)
    legal = rules.legal_moves(state)
    assert strategy.choose(state, legal, TimeBudget(1e9)) in legal


def test_strategy_beats_random_play() -> None:
    # 席を入れ替えて 12 ゲーム。評価値つきの方針は、無作為の方針に勝ち越す
    wins = losses = 0
    for seed in range(6):
        for strategy_seat in (0, 1):
            policies = [random_policy(random.Random(seed * 7 + 1)) for _ in range(2)]
            policies[strategy_seat] = strategy_policy(seed, samples=2)
            result = play_game(seed, tuple(policies))
            outcome = result.outcomes[strategy_seat]
            wins += outcome == "win"
            losses += outcome == "lose"
    assert wins > losses, (wins, losses)


def test_unknown_cards_add_no_value_and_cards_over_the_limit_are_penalised() -> None:
    # 読めない札は置けないので、価値を足さない。手札の上限(7 枚)を超えた札は減点する
    from dataclasses import replace

    from bglm.plugins.wingspan.logic.evaluation import DEFAULT_WEIGHTS, evaluate
    from bglm.plugins.wingspan.logic.models import UNKNOWN_CARD

    rules = WingspanRules()
    base = initial_state(default_table(), 1)
    board = base.players[0]
    empty = base.with_player(0, replace(board, hand=()))
    with_unknown = base.with_player(0, replace(board, hand=(UNKNOWN_CARD,) * 3))
    assert evaluate(with_unknown, rules, 0) == evaluate(empty, rules, 0)
    seven = base.with_player(0, replace(board, hand=(UNKNOWN_CARD,) * 7))
    eight = base.with_player(0, replace(board, hand=(UNKNOWN_CARD,) * 8))
    drop = evaluate(seven, rules, 0) - evaluate(eight, rules, 0)
    assert abs(drop - DEFAULT_WEIGHTS.hand_over) < 1e-9
