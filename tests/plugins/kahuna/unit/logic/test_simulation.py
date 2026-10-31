"""自己対戦(logic だけで1ゲームを完走する)。ルールの矛盾・無限ループ・不変条件の破れを見つける。"""

import random
from collections import Counter

import pytest
from tests.plugins.kahuna.support.helpers import ME, OPP, island, line

from bglm.plugins.kahuna.logic.models import (
    DiscardCard,
    DrawDeck,
    PassDraw,
    PlaceStick,
    Player,
)
from bglm.plugins.kahuna.logic.rules import KahunaRules, Ruleset
from bglm.plugins.kahuna.logic.simulation import Game, RandomChooser, play_game
from bglm.plugins.kahuna.logic.strategy import KahunaStrategy

RULES = KahunaRules()


def new_game(seed: int = 0) -> Game:
    return Game(random.Random(seed))


class TestDeal:
    """GETTING STARTED: 24枚を混ぜ、各3枚を配り、3枚を表向きにし、残りを山札にする。"""

    def test_hands_market_and_deck_sizes(self) -> None:
        game = new_game()

        assert [len(h) for h in game.hands] == [3, 3]
        assert len(game.market) == 3
        assert len(game.deck) == 15  # 実機の開始時の山札の枚数と一致

    def test_every_island_has_exactly_two_cards(self) -> None:
        game = new_game()
        cards = game.hands[0] + game.hands[1] + game.market + game.deck

        assert sorted(cards) == sorted([i for i in range(12) for _ in range(2)])

    def test_different_seeds_deal_differently(self) -> None:
        assert new_game(1).deck != new_game(2).deck

    def test_the_same_seed_deals_the_same(self) -> None:
        assert new_game(5).deck == new_game(5).deck


class TestView:
    def test_the_second_player_sees_the_owners_swapped(self) -> None:
        game = new_game()
        game.sticks = tuple(Player.ME if n == 0 else None for n in range(27))  # 先手の杖コマ

        assert game.view(0).sticks[0] == ME
        assert game.view(1).sticks[0] == OPP

    def test_a_player_sees_only_their_own_hand(self) -> None:
        game = new_game()

        assert sorted(game.view(0).hand) == sorted(game.hands[0])
        assert sorted(game.view(1).hand) == sorted(game.hands[1])

    def test_scores_are_listed_own_first(self) -> None:
        game = new_game()
        game.scores = [3, 1]

        assert game.view(0).scores == (3, 1)
        assert game.view(1).scores == (1, 3)

    def test_deck_count_does_not_reveal_the_order(self) -> None:
        assert new_game().view(0).deck_count == 15


class TestApply:
    def test_an_illegal_move_raises(self) -> None:
        game = new_game()

        with pytest.raises(ValueError, match="合法手ではない"):
            game.apply(0, PlaceStick(card=99, line=0), RULES)

    def test_placing_moves_the_card_to_the_discard_pile(self) -> None:
        game = new_game()
        card = game.hands[0][0]
        free = game.board.lines_of[card][0]

        turn_over = game.apply(0, PlaceStick(card, free), RULES)

        assert not turn_over
        assert game.sticks[free] == Player(0)
        assert game.discard == [card]
        assert len(game.hands[0]) == 2

    def test_drawing_from_the_deck_ends_the_turn_and_grows_the_hand(self) -> None:
        game = new_game()

        turn_over = game.apply(0, DrawDeck(), RULES)

        assert turn_over
        assert len(game.hands[0]) == 4
        assert len(game.deck) == 14

    def test_drawing_from_the_market_refills_it_from_the_deck(self) -> None:
        game = new_game()
        card = game.market[0]

        from bglm.plugins.kahuna.logic.models import DrawMarket

        game.apply(0, DrawMarket(card), RULES)

        assert len(game.market) == 3
        assert len(game.deck) == 14

    def test_passing_forces_the_opponent_to_draw(self) -> None:
        game = new_game()

        game.apply(0, PassDraw(), RULES)

        assert game.must_draw == [False, True]
        assert PassDraw() not in RULES.legal_moves(game.view(1))

    def test_a_forced_player_who_draws_is_free_again(self) -> None:
        game = new_game()
        game.apply(0, PassDraw(), RULES)

        game.apply(1, DrawDeck(), RULES)

        assert game.must_draw == [False, False]

    def test_a_discard_goes_to_the_discard_pile_without_ending_the_turn(self) -> None:
        game = new_game()
        card = game.hands[0][0]

        assert not game.apply(0, DiscardCard(card), RULES)
        assert game.discard == [card]


class TestSettlement:
    """IN-BETWEEN SCORE: 最後の1枚が取られたら決算。"""

    def finished_round(self, round_no: int, mine: int, theirs: int) -> Game:
        game = new_game()
        game.round = round_no
        stones = [None] * 12
        for i in range(mine):
            stones[i] = Player.ME
        for i in range(mine, mine + theirs):
            stones[i] = Player.OPPONENT
        game.stones = tuple(stones)
        return game

    def test_round_one_gives_one_point_to_the_leader(self) -> None:
        game = self.finished_round(1, mine=2, theirs=1)

        game.settle_round()

        assert game.scores == [1, 0]
        assert game.round == 2

    def test_round_two_gives_two_points(self) -> None:
        game = self.finished_round(2, mine=0, theirs=1)

        game.settle_round()

        assert game.scores == [0, 2]
        assert game.round == 3

    def test_equal_islands_score_nothing(self) -> None:
        game = self.finished_round(1, mine=2, theirs=2)

        game.settle_round()

        assert game.scores == [0, 0]

    def test_the_new_deck_is_built_from_the_discard_pile_and_hands_stay(self) -> None:
        game = new_game()
        game.discard = game.deck + game.market  # 山札と場札を使い切って、すべて捨て札になった状態
        game.deck, game.market = [], []
        hands = [h[:] for h in game.hands]

        game.settle_round()

        assert game.hands == hands
        assert len(game.market) == 3
        assert len(game.deck) == 15
        assert game.discard == []
        game.check_invariants()

    def test_final_scoring_awards_the_difference_and_decides_the_winner(self) -> None:
        game = self.finished_round(3, mine=4, theirs=1)
        game.scores = [1, 2]

        game.final_scoring()

        assert game.scores == [4, 2]  # 3ラウンド目の差は 3
        assert game.round3_points == [3, 0]
        assert game.over
        assert game.winner == Player.ME

    def test_equal_totals_are_decided_by_the_third_round_points(self) -> None:
        """A TIE OR ENDING IN BETWEEN: 同点なら、3ラウンド目の得点が多い方の勝ち。"""
        game = self.finished_round(3, mine=1, theirs=3)  # 3ラウンド目は相手が差2で2点
        game.scores = [2, 0]  # 決算後に 2-2 の同点になる

        game.final_scoring()

        assert game.scores == [2, 2]
        assert game.winner == Player.OPPONENT

    def test_equal_totals_and_third_round_are_decided_by_the_number_of_sticks(self) -> None:
        game = self.finished_round(3, mine=2, theirs=2)  # 3ラウンド目は0対0
        game.scores = [3, 3]
        game.sticks = tuple(
            Player.ME if n < 3 else Player.OPPONENT if n < 5 else None for n in range(27)
        )

        game.final_scoring()

        assert game.winner == Player.ME  # 杖コマは 3本 対 2本

    def test_a_complete_tie_is_a_draw(self) -> None:
        game = self.finished_round(3, mine=2, theirs=2)
        game.scores = [3, 3]
        game.sticks = tuple(
            Player.ME if n < 2 else Player.OPPONENT if n < 4 else None for n in range(27)
        )

        game.final_scoring()

        assert game.over
        assert game.winner is None


class TestFullGames:
    def test_random_games_always_finish_with_the_invariants_intact(self) -> None:
        """不変条件(カードの総数、手札上限、支配の整合)は、手ごとに Game.check_invariants が確認する。"""
        for seed in range(40):
            rng = random.Random(seed)

            result = play_game((RandomChooser(rng), RandomChooser(rng)), rng)

            assert result.turns > 0

    def test_a_full_game_goes_through_three_rounds(self) -> None:
        rounds_seen: set[int] = set()
        rng = random.Random(1)

        play_game(
            (RandomChooser(rng), RandomChooser(rng)),
            rng,
            ruleset=Ruleset(early_end_without_sticks=False),
            on_move=lambda g: rounds_seen.add(g.round),
        )

        assert rounds_seen == {1, 2, 3}

    def test_each_player_takes_one_more_turn_after_the_last_card_of_round_three(self) -> None:
        """FINAL SCORE AND END OF THE GAME: 最後のカードが取られたら、各プレイヤーがもう1手番。"""
        marks: dict[str, int] = {}
        rng = random.Random(1)

        def watch(game: Game) -> None:
            if game.round == 3 and game.cards_left == 0:
                marks.setdefault("last_card_turn", game.turns)

        result = play_game(
            (RandomChooser(rng), RandomChooser(rng)),
            rng,
            ruleset=Ruleset(early_end_without_sticks=False),
            on_move=watch,
        )

        assert result.turns - marks["last_card_turn"] == 2

    def test_a_game_without_early_end_never_reports_one(self) -> None:
        for seed in range(30):
            rng = random.Random(seed)
            strategy = KahunaStrategy()

            result = play_game(
                (strategy, RandomChooser(rng)), rng, ruleset=Ruleset(early_end_without_sticks=False)
            )

            assert not result.early_end

    def test_with_early_end_switched_on_a_game_can_end_early(self) -> None:
        """A TIE OR ENDING IN BETWEEN(アプリ内ルール。既定では適用しない)。"""
        strategy = KahunaStrategy()
        early = 0
        for seed in range(40):
            rng = random.Random(seed)

            result = play_game(
                (strategy, RandomChooser(rng)), rng, ruleset=Ruleset(early_end_without_sticks=True)
            )

            if result.early_end:
                early += 1
                assert result.winner == Player(0)  # 杖コマを失ったランダム側が負ける

        assert early > 0

    def test_by_default_no_game_ends_early(self) -> None:
        strategy = KahunaStrategy()
        for seed in range(40):
            rng = random.Random(seed)

            assert not play_game((strategy, RandomChooser(rng)), rng).early_end

    def test_the_same_seed_gives_the_same_game(self) -> None:
        def run() -> tuple:  # type: ignore[type-arg]
            rng = random.Random(7)
            result = play_game((RandomChooser(rng), RandomChooser(rng)), rng)
            return result.winner, result.scores, result.turns

        assert run() == run()

    def test_the_two_seats_are_balanced_for_random_play(self) -> None:
        wins: Counter[Player | None] = Counter()
        for seed in range(200):
            rng = random.Random(seed)
            wins[play_game((RandomChooser(rng), RandomChooser(rng)), rng).winner] += 1

        assert abs(wins[Player(0)] - wins[Player(1)]) < 40  # 先手・後手の有利不利がない

    @pytest.mark.parametrize("first", [True, False])
    def test_the_strategy_beats_random_play_from_either_seat(self, first: bool) -> None:
        strategy = KahunaStrategy()
        wins = 0
        games = 30
        for seed in range(games):
            rng = random.Random(1000 + seed)
            choosers = (strategy, RandomChooser(rng)) if first else (RandomChooser(rng), strategy)
            result = play_game(choosers, rng)
            seat = 0 if first else 1
            wins += result.winner is not None and result.winner.value == seat

        assert wins >= 0.9 * games

    def test_passing_forever_cannot_stall_the_game(self) -> None:
        """DRAWING AN ISLAND CARD: 引かずに終えると相手が必ず引く。だから山札は減り続ける。"""

        class AlwaysPass:
            def choose(self, state, legal, budget):  # type: ignore[no-untyped-def]
                return PassDraw() if PassDraw() in legal else legal[0]

        rng = random.Random(0)

        result = play_game((AlwaysPass(), AlwaysPass()), rng)

        assert result.turns < 600

    def test_a_game_that_never_ends_is_reported_not_looped_forever(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("bglm.plugins.kahuna.logic.simulation.MAX_TURNS", 3)
        rng = random.Random(0)

        with pytest.raises(RuntimeError, match="無限ループ"):
            play_game((RandomChooser(rng), RandomChooser(rng)), rng)


def test_line_helper_agrees_with_the_board_used_by_the_game() -> None:
    game = new_game()

    assert game.board.line_between(island("ALOA"), island("BARI")) == line("ALOA", "BARI")
