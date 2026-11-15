"""MaquisStrategy のテスト。最優先の制約(全団員が捕縛される配置を避ける)と、行動の選び方。"""

import random
from dataclasses import replace

from bglm.core.models import TimeBudget
from bglm.plugins.maquis.logic.models import EndPhase, MaquisState, Phase, Place, Resolve
from bglm.plugins.maquis.logic.patrol import PatrolCard, PatrolDeck
from bglm.plugins.maquis.logic.rules import MaquisRules, initial_state
from bglm.plugins.maquis.logic.strategy import MaquisStrategy, load_weights

# どの巡回も、まず ① の cafe に出る(cafe が埋まっていれば ② の grocer)。畑(西)は cafe を通らないと戻れない
CAFE_FIRST: PatrolCard = ("cafe", "grocer", "pont_leveque")


def strategy(seed: int = 0) -> MaquisStrategy:
    return MaquisStrategy(rng=random.Random(seed))


def budget() -> TimeBudget:
    return TimeBudget(30.0)


def test_weights_load() -> None:
    w = load_weights()
    assert w.defeat > w.agent * 10 > 0
    assert w.samples >= 1


def test_avoids_the_placement_that_strands_the_last_agent() -> None:
    # 団員が1人だけ。畑(西)に置くと、巡回が cafe に出て戻れず、全員捕縛 = 敗北
    state = replace(
        initial_state(),
        agents_total=1,
        unplaced=1,
        deck=PatrolDeck.of([CAFE_FIRST] * 5),
    )
    rules = MaquisRules()
    legal = rules.legal_moves(state)
    assert Place("field_w") in legal
    for seed in range(5):
        move = strategy(seed).choose(state, legal, budget())
        assert isinstance(move, Place)
        assert move.location != "field_w"
        # 選んだ配置は、巡回が出た後も戻れる
        placed = rules.place_patrol(rules.apply(state, move), CAFE_FIRST)
        assert not rules.apply(rules.apply(placed, EndPhase()), EndPhase()).defeated


def test_prefers_a_productive_location_when_safe() -> None:
    state = replace(initial_state(), agents_total=1, unplaced=1, deck=PatrolDeck.of([CAFE_FIRST]))
    move = strategy().choose(state, MaquisRules().legal_moves(state), budget())
    assert isinstance(move, Place)
    assert move.location in {"doctor", "grocer", "mission_b"}  # 資材か★が増える地点


def test_placement_after_all_agents_is_end_phase() -> None:
    state = replace(initial_state(), unplaced=0, agents=("doctor",))
    rules = MaquisRules()
    assert strategy().choose(state, rules.legal_moves(state), budget()) == EndPhase()


def action_state(**kw: object) -> MaquisState:
    return replace(initial_state(), phase=Phase.ACTION, unplaced=0, **kw)  # type: ignore[arg-type]


def test_action_phase_resolves_a_gaining_action_then_ends() -> None:
    state = action_state(agents=("doctor",))
    rules = MaquisRules()
    s = strategy()
    move = s.choose(state, rules.legal_moves(state), budget())
    assert move == Resolve("doctor", 0)
    after = rules.apply(state, move)
    assert s.choose(after, rules.legal_moves(after), budget()) == EndPhase()


def test_action_phase_does_not_spend_food_for_nothing_it_values() -> None:
    # カフェの勧誘(食料1 → 団員+1)は、団員の価値が食料より高いので実行する
    state = action_state(agents=("cafe",), resources=replace(initial_state().resources, food=1))
    rules = MaquisRules()
    assert strategy().choose(state, rules.legal_moves(state), budget()) == Resolve("cafe", 0)


def test_runs_a_whole_game_with_only_legal_moves() -> None:
    rules = MaquisRules()
    s = MaquisStrategy(weights=replace(load_weights(), samples=8), rng=random.Random(1))
    state = initial_state()
    rng = random.Random(7)
    for _ in range(200):
        if rules.is_terminal(state):
            break
        legal = rules.legal_moves(state)
        move = s.choose(state, legal, budget())
        assert move in legal
        state = rules.apply(state, move)
        if isinstance(move, Place):
            card = rng.choice(
                [c for c, n in state.deck.remaining for _ in range(n)] or [CAFE_FIRST]
            )
            try:
                state = rules.place_patrol(state, card)
            except ValueError:
                pass
        if isinstance(move, EndPhase) and state.phase is Phase.PLACEMENT:
            assert state.turn >= 2
