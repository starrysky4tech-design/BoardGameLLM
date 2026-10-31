from dataclasses import replace

import pytest
from tests.plugins.kahuna.support.helpers import BOARD, ME, OPP, island, make_state

from bglm.core.models import TimeBudget
from bglm.plugins.kahuna.logic.models import (
    DiscardCard,
    DrawDeck,
    DrawMarket,
    PassDraw,
    PlaceStick,
    RemoveStick,
)
from bglm.plugins.kahuna.logic.rules import KahunaRules, Ruleset, controls
from bglm.plugins.kahuna.logic.strategy import (
    WIN_SCORE,
    KahunaStrategy,
    StrategyWeights,
    load_weights,
)

RULES = KahunaRules()
STRATEGY = KahunaStrategy()


def choose(state, strategy: KahunaStrategy = STRATEGY):  # type: ignore[no-untyped-def]
    legal = RULES.legal_moves(state)
    return strategy.choose(state, legal, TimeBudget(10.0))


def mirror(state):  # type: ignore[no-untyped-def]
    """自分と相手を入れ替えた盤面。"""
    swap = {ME: OPP, OPP: ME, None: None}
    return replace(
        state,
        sticks=tuple(swap[o] for o in state.sticks),
        stones=tuple(swap[o] for o in state.stones),
        scores=state.scores[::-1],
    )


class TestWeights:
    def test_the_config_file_matches_the_defaults(self) -> None:
        """strategy.toml とコード上の既定値がずれていないこと。"""
        assert load_weights() == StrategyWeights()

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"stone_by_round": (10.0, 14.0)},
            {"stone_by_round": (10.0, -1.0, 20.0)},
            {"late_cards": -1},
            {"late_multiplier": 0.9},
            {"near_control": -0.1},
            {"stick": -1.0},
            {"card_cost": -1.0},
            {"min_gain": -0.1},
            {"deck_card_fraction": 1.1},
            {"deck_card_fraction": -0.1},
        ],
    )
    def test_out_of_range_weights_are_rejected(self, kwargs: dict) -> None:  # type: ignore[type-arg]
        with pytest.raises(ValueError):
            StrategyWeights(**kwargs)

    def test_boundary_values_are_accepted(self) -> None:
        StrategyWeights(late_multiplier=1.0, deck_card_fraction=0.0, card_cost=0.0, min_gain=0.0)
        StrategyWeights(deck_card_fraction=1.0)


class TestEvaluate:
    def test_more_stones_is_better(self) -> None:
        ahead = make_state(stones={"ALOA": ME})

        assert STRATEGY.evaluate(ahead) > STRATEGY.evaluate(make_state())

    def test_swapping_the_players_negates_the_score(self) -> None:
        state = make_state(
            {("ALOA", "BARI"): ME, ("ALOA", "DUDA"): ME, ("BARI", "COCO"): OPP},
            stones={"ALOA": ME, "COCO": OPP},
            round=2,
        )

        assert STRATEGY.evaluate(mirror(state)) == pytest.approx(-STRATEGY.evaluate(state))

    def test_an_empty_board_is_neutral(self) -> None:
        assert STRATEGY.evaluate(make_state()) == 0.0

    def test_later_rounds_weigh_the_stone_lead_more(self) -> None:
        one = [STRATEGY.evaluate(make_state(stones={"ALOA": ME}, round=r)) for r in (1, 2, 3)]

        assert one[0] < one[1] < one[2]

    def test_the_lead_weighs_more_when_the_round_is_about_to_end(self) -> None:
        early = make_state(stones={"ALOA": ME}, deck_count=10)
        late = make_state(stones={"ALOA": ME}, deck_count=1)

        assert STRATEGY.evaluate(late) > STRATEGY.evaluate(early)

    def test_one_stick_away_from_control_is_counted(self) -> None:
        state = make_state({("ALOA", "BARI"): ME})  # ALOA(3本)に1本: あと1本で支配

        assert STRATEGY._near_control(state, ME) == 1
        assert STRATEGY._near_control(state, OPP) == 0

    def test_it_counts_the_opponents_islands_for_the_opponent(self) -> None:
        state = make_state({("ALOA", "BARI"): OPP})

        assert STRATEGY._near_control(state, OPP) == 1
        assert STRATEGY._near_control(state, ME) == 0

    def test_an_island_with_no_free_line_is_not_near(self) -> None:
        """ALOA は自分1本だが、残り2本を相手に埋められていて、置ける点線が無い。"""
        blocked = make_state({("ALOA", "BARI"): ME, ("ALOA", "DUDA"): OPP, ("ALOA", "HUNA"): OPP})

        assert STRATEGY._near_control(blocked, ME) == 0

    def test_an_island_already_controlled_is_not_near(self) -> None:
        state = make_state({("ALOA", "BARI"): ME, ("ALOA", "DUDA"): ME}, stones={"ALOA": ME})

        assert STRATEGY._near_control(state, ME) == 0

    def test_two_sticks_in_a_five_line_island_are_still_one_away(self) -> None:
        state = make_state({("BARI", "COCO"): ME, ("BARI", "DUDA"): ME})  # BARI(5本)に2本

        assert STRATEGY._near_control(state, ME) >= 1

    def test_winning_and_losing_states(self) -> None:
        assert STRATEGY.evaluate(make_state(over=True, winner=ME)) == WIN_SCORE
        assert STRATEGY.evaluate(make_state(over=True, winner=OPP)) == -WIN_SCORE
        assert STRATEGY.evaluate(make_state(over=True, winner=None)) == 0.0


class TestChoose:
    def test_takes_an_island_when_one_stick_wins_it(self) -> None:
        state = make_state({("ALOA", "BARI"): ME}, hand=("ALOA",), market=("LALE",))

        move = choose(state)

        assert isinstance(move, PlaceStick)
        after = RULES.apply(state, move)
        assert controls(BOARD, after.sticks, island("ALOA"), ME)

    def test_prefers_a_removal_that_breaks_the_opponents_control(self) -> None:
        elai = {
            ("BARI", "ELAI"): OPP,
            ("DUDA", "ELAI"): OPP,
            ("ELAI", "FAAA"): OPP,
            ("ELAI", "HUNA"): OPP,
        }
        state = make_state(elai, stones={"ELAI": OPP}, hand=("ELAI", "BARI"))

        move = choose(state)

        assert isinstance(move, RemoveStick)
        after = RULES.apply(state, move)
        assert after.stones[island("ELAI")] is None

    def test_takes_the_win_by_removing_the_last_opponent_stick_when_early_end_applies(self) -> None:
        rules = KahunaRules(ruleset=Ruleset(early_end_without_sticks=True))
        strategy = KahunaStrategy(rules=rules)
        state = make_state(
            {("ELAI", "FAAA"): OPP, ("ALOA", "BARI"): ME}, hand=("ELAI", "FAAA"), round=2
        )

        move = strategy.choose(state, rules.legal_moves(state), TimeBudget(10.0))

        assert rules.apply(state, move).over

    def test_does_not_play_a_card_for_no_gain_and_draws_instead(self) -> None:
        costly = KahunaStrategy(weights=StrategyWeights(card_cost=100.0))
        state = make_state(hand=("ALOA",), market=("BARI",), deck_count=5)

        move = choose(state, costly)

        assert isinstance(move, DrawMarket | DrawDeck)

    def test_draws_the_market_card_that_wins_an_island(self) -> None:
        state = make_state(
            {("ALOA", "BARI"): ME}, hand=(), market=("LALE", "ALOA", "COCO"), deck_count=5
        )
        costly = KahunaStrategy(weights=StrategyWeights(card_cost=100.0))

        move = choose(state, costly)

        assert move == DrawMarket(island("ALOA"))

    def test_with_a_full_hand_it_discards_the_least_useful_card(self) -> None:
        """LALE の3本はすべて相手に埋められていて使えない。5枚で引けないので、先にそれを捨てる。"""
        sticks = {("HUNA", "LALE"): OPP, ("IFFI", "LALE"): OPP, ("KAHU", "LALE"): OPP}
        state = make_state(
            sticks,
            hand=("LALE", "ALOA", "BARI", "COCO", "DUDA"),
            market=("FAAA",),
            deck_count=5,
        )
        costly = KahunaStrategy(weights=StrategyWeights(card_cost=100.0))

        move = choose(state, costly)

        assert move == DiscardCard(island("LALE"))

    def test_passes_only_when_nothing_can_be_drawn(self) -> None:
        costly = KahunaStrategy(weights=StrategyWeights(card_cost=100.0))
        state = make_state(hand=("ALOA",), market=(), deck_count=0)

        assert choose(state, costly) == PassDraw()

    def test_with_a_full_hand_and_nothing_to_draw_it_passes_instead_of_discarding(self) -> None:
        costly = KahunaStrategy(weights=StrategyWeights(card_cost=100.0))
        state = make_state(hand=("ALOA", "BARI", "COCO", "DUDA", "ELAI"), market=(), deck_count=0)

        assert choose(state, costly) == PassDraw()

    def test_an_expired_budget_still_returns_a_legal_move(self) -> None:
        state = make_state({("ALOA", "BARI"): ME}, hand=("ALOA", "BARI"), market=("COCO",))
        ticks = iter([0.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0])
        budget = TimeBudget(1.0, lambda: next(ticks, 100.0))
        legal = RULES.legal_moves(state)

        assert STRATEGY.choose(state, legal, budget) in legal

    def test_no_legal_moves_raises(self) -> None:
        with pytest.raises(ValueError, match="合法手が無い"):
            STRATEGY.choose(make_state(), [], TimeBudget(1.0))

    def test_the_choice_is_deterministic(self) -> None:
        state = make_state(
            {("ALOA", "BARI"): ME, ("BARI", "COCO"): OPP},
            hand=("ALOA", "COCO", "ELAI"),
            market=("FAAA", "GOLA", "HUNA"),
        )

        assert {choose(state) for _ in range(5)} == {choose(state)}

    def test_the_chosen_move_is_always_legal(self) -> None:
        for hand in [("ALOA",), ("ELAI", "ELAI"), ("LALE", "KAHU", "JOJO", "IFFI", "HUNA")]:
            state = make_state({("ELAI", "FAAA"): OPP}, hand=hand, market=("COCO",))
            assert choose(state) in RULES.legal_moves(state)
