"""Kahuna のルール。期待値はアプリ内 RULES(docs/ideas/Kahuna_アプリ内ルール.md)の記述から手で作った。

テスト名・docstring の大文字のページ名は、アプリ内 RULES のページ名。
"""

from dataclasses import replace

import pytest
from tests.plugins.kahuna.support.helpers import (
    BOARD,
    ME,
    OPP,
    empty_sticks,
    empty_stones,
    island,
    line,
    make_state,
)

from bglm.plugins.kahuna.logic.models import (
    UNKNOWN_CARD,
    DiscardCard,
    DrawDeck,
    DrawMarket,
    PassDraw,
    PlaceStick,
    RemoveStick,
)
from bglm.plugins.kahuna.logic.rules import (
    KahunaRules,
    Ruleset,
    controls,
    count_sticks,
    decide_winner,
    early_end_winner,
    place_stick,
    removal_pair_matches,
    remove_stick,
    round_points,
)

RULES = KahunaRules()
RULES_EARLY_END = KahunaRules(ruleset=Ruleset(early_end_without_sticks=True))


def sticks_of(owner_by_line: dict[tuple[str, str], object]) -> tuple[object, ...]:
    sticks = empty_sticks()
    for (a, b), owner in owner_by_line.items():
        sticks[line(a, b)] = owner  # type: ignore[call-overload]
    return tuple(sticks)


class TestControl:
    """KAHUNA STONE PLACEMENT: 点線の半分より多くに杖コマがあれば支配する。"""

    @pytest.mark.parametrize(
        ("name", "owned", "expected"),
        [
            ("ALOA", 1, False), ("ALOA", 2, True),   # 3本: 2本で過半数
            ("COCO", 2, False), ("COCO", 3, True),   # 4本: ちょうど半分では足りない
            ("BARI", 2, False), ("BARI", 3, True),   # 5本: 3本
            ("ELAI", 3, False), ("ELAI", 4, True),   # 6本: ちょうど半分では足りない
        ],
    )  # fmt: skip
    def test_majority_threshold(self, name: str, owned: int, expected: bool) -> None:
        sticks = empty_sticks()
        for n in BOARD.lines_of[island(name)][:owned]:
            sticks[n] = ME

        assert controls(BOARD, tuple(sticks), island(name), ME) is expected

    def test_opponent_sticks_do_not_count_for_me(self) -> None:
        sticks = sticks_of({("ALOA", "BARI"): OPP, ("ALOA", "DUDA"): OPP})

        assert not controls(BOARD, sticks, island("ALOA"), ME)  # type: ignore[arg-type]


class TestPlaceStick:
    def place(self, sticks: dict, stones: dict, a: str, b: str, player=ME):  # type: ignore[no-untyped-def]
        stone_list = empty_stones()
        for name, owner in stones.items():
            stone_list[island(name)] = owner
        return place_stick(
            BOARD,
            sticks_of(sticks),
            tuple(stone_list),
            line(a, b),
            player,  # type: ignore[arg-type]
        )

    def test_reaching_a_majority_places_a_stone(self) -> None:
        _, stones = self.place({("ALOA", "BARI"): ME}, {}, "ALOA", "DUDA")

        assert stones[island("ALOA")] == ME

    def test_one_stick_short_of_a_majority_places_no_stone(self) -> None:
        _, stones = self.place({}, {}, "ALOA", "DUDA")

        assert stones[island("ALOA")] is None

    def test_gaining_control_removes_the_opponents_sticks_on_that_island(self) -> None:
        sticks, _ = self.place({("ALOA", "BARI"): ME, ("ALOA", "HUNA"): OPP}, {}, "ALOA", "DUDA")

        assert sticks[line("ALOA", "HUNA")] is None
        assert sticks[line("ALOA", "BARI")] == ME

    def test_removed_sticks_cost_the_opponent_a_neighboring_stone(self) -> None:
        """HUNA(5本)をOPPが3本で支配している。ALOA を奪うと ALOA-HUNA が消え、HUNA は2本になる。"""
        opp_huna = {("ALOA", "HUNA"): OPP, ("DUDA", "HUNA"): OPP, ("ELAI", "HUNA"): OPP}
        sticks, stones = self.place(
            {**opp_huna, ("ALOA", "BARI"): ME}, {"HUNA": OPP}, "ALOA", "DUDA"
        )

        assert stones[island("HUNA")] is None
        assert sticks[line("DUDA", "HUNA")] == OPP  # 取り除かれるのは ALOA に接する分だけ

    def test_neighbor_keeps_its_stone_if_still_a_majority(self) -> None:
        """HUNA をOPPが4本で支配。1本取り除かれても3本(>2.5)で支配が続く。"""
        opp_huna = {
            ("ALOA", "HUNA"): OPP,
            ("DUDA", "HUNA"): OPP,
            ("ELAI", "HUNA"): OPP,
            ("HUNA", "IFFI"): OPP,
        }
        _, stones = self.place({**opp_huna, ("ALOA", "BARI"): ME}, {"HUNA": OPP}, "ALOA", "DUDA")

        assert stones[island("HUNA")] == OPP

    def test_one_stick_can_win_both_of_its_islands(self) -> None:
        mine = {
            ("ALOA", "DUDA"): ME,  # ALOA(3本)の1本目
            ("BARI", "COCO"): ME,
            ("BARI", "DUDA"): ME,  # BARI(5本)の2本目まで
        }
        _, stones = self.place(mine, {}, "ALOA", "BARI")

        assert stones[island("ALOA")] == ME
        assert stones[island("BARI")] == ME

    def test_the_opponent_gains_control_by_the_same_rule(self) -> None:
        sticks, stones = self.place(
            {("ALOA", "BARI"): OPP, ("ALOA", "HUNA"): ME}, {}, "ALOA", "DUDA", player=OPP
        )

        assert stones[island("ALOA")] == OPP
        assert sticks[line("ALOA", "HUNA")] is None

    def test_placing_on_an_occupied_line_raises(self) -> None:
        with pytest.raises(ValueError, match="空いていない"):
            self.place({("ALOA", "BARI"): OPP}, {}, "ALOA", "BARI")

    def test_input_is_not_mutated(self) -> None:
        original = sticks_of({("ALOA", "BARI"): ME})

        place_stick(BOARD, original, tuple(empty_stones()), line("ALOA", "DUDA"), ME)

        assert original == sticks_of({("ALOA", "BARI"): ME})


class TestRemoveStick:
    """REMOVAL OF AN OPPONENT'S BRIDGE と KAHUNA STONE PLACEMENT(支配を失うと石も外れる)。"""

    def stones_on(self, name: str, owner) -> tuple:  # type: ignore[no-untyped-def]
        stones = empty_stones()
        stones[island(name)] = owner
        return tuple(stones)

    def test_removing_below_a_majority_removes_the_stone(self) -> None:
        elai = {
            (a, "ELAI") if a < "ELAI" else ("ELAI", a): ME for a in ("BARI", "DUDA", "FAAA", "HUNA")
        }
        sticks = sticks_of(elai)  # ELAI(6本)に4本 = 支配

        new_sticks, stones = remove_stick(
            BOARD,
            sticks,
            self.stones_on("ELAI", ME),
            line("BARI", "ELAI"),  # type: ignore[arg-type]
        )

        assert stones[island("ELAI")] is None
        assert new_sticks[line("BARI", "ELAI")] is None

    def test_a_remaining_majority_keeps_the_stone(self) -> None:
        elai = {
            (a, "ELAI") if a < "ELAI" else ("ELAI", a): ME
            for a in ("BARI", "DUDA", "FAAA", "HUNA", "IFFI")
        }
        sticks = sticks_of(elai)  # 5本

        _, stones = remove_stick(
            BOARD,
            sticks,
            self.stones_on("ELAI", ME),
            line("BARI", "ELAI"),  # type: ignore[arg-type]
        )

        assert stones[island("ELAI")] == ME

    def test_both_ends_can_lose_their_stones(self) -> None:
        """ALOA-DUDA を取り除くと、ALOA(2本→1本)と DUDA(3本→2本)の両方が過半数を割る。"""
        mine = {
            ("ALOA", "DUDA"): ME,
            ("ALOA", "BARI"): ME,
            ("BARI", "DUDA"): ME,
            ("DUDA", "HUNA"): ME,
        }
        stones = empty_stones()
        stones[island("ALOA")] = ME
        stones[island("DUDA")] = ME

        _, new_stones = remove_stick(
            BOARD,
            sticks_of(mine),
            tuple(stones),
            line("ALOA", "DUDA"),  # type: ignore[arg-type]
        )

        assert new_stones[island("ALOA")] is None
        assert new_stones[island("DUDA")] is None

    def test_removing_from_an_empty_line_raises(self) -> None:
        with pytest.raises(ValueError, match="杖コマが無い"):
            remove_stick(BOARD, tuple(empty_sticks()), tuple(empty_stones()), 0)


class TestRemovalPair:
    """REMOVAL OF AN OPPONENT'S BRIDGE: 組の2枚は、その橋が結ぶ2島の名前だけ。"""

    @pytest.mark.parametrize(
        ("cards", "expected"),
        [
            (("ELAI", "FAAA"), True),
            (("FAAA", "FAAA"), True),
            (("ELAI", "ELAI"), True),
            (("ELAI", "BARI"), False),
            (("BARI", "COCO"), False),
        ],
    )
    def test_pairs_for_the_elai_faaa_bridge(self, cards: tuple[str, str], expected: bool) -> None:
        pair = (island(cards[0]), island(cards[1]))

        assert removal_pair_matches(BOARD, pair, line("ELAI", "FAAA")) is expected


class TestScoring:
    """IN-BETWEEN SCORE / FINAL SCORE AND END OF THE GAME。"""

    def stones(self, mine: int, theirs: int) -> tuple:  # type: ignore[type-arg]
        stones = empty_stones()
        for i in range(mine):
            stones[i] = ME
        for i in range(mine, mine + theirs):
            stones[i] = OPP
        return tuple(stones)

    @pytest.mark.parametrize(
        ("round_no", "mine", "theirs", "expected"),
        [
            (1, 3, 1, (1, 0)),   # 1ラウンド目: 多い方が1点(差は関係ない)
            (1, 1, 5, (0, 1)),
            (2, 3, 1, (2, 0)),   # 2ラウンド目: 多い方が2点
            (2, 0, 1, (0, 2)),
            (3, 3, 1, (2, 0)),   # 3ラウンド目: 島の数の差
            (3, 1, 6, (0, 5)),
            (1, 2, 2, (0, 0)),   # 同数なら得点なし
            (3, 0, 0, (0, 0)),
            (3, 4, 4, (0, 0)),
        ],
    )  # fmt: skip
    def test_round_points(
        self, round_no: int, mine: int, theirs: int, expected: tuple[int, int]
    ) -> None:
        assert round_points(round_no, self.stones(mine, theirs)) == expected


class TestWinner:
    """A TIE OR ENDING IN BETWEEN: 合計点 → 3ラウンド目の得点 → 盤上の杖コマの数 → 引き分け。"""

    def test_higher_total_wins(self) -> None:
        assert decide_winner((3, 2), (0, 5), tuple(empty_sticks())) == ME

    def test_tied_total_goes_to_the_third_round_points(self) -> None:
        assert decide_winner((3, 3), (1, 2), tuple(empty_sticks())) == OPP

    def test_still_tied_goes_to_the_number_of_sticks(self) -> None:
        sticks = sticks_of({("ALOA", "BARI"): ME, ("ALOA", "DUDA"): ME, ("BARI", "COCO"): OPP})

        assert decide_winner((3, 3), (1, 1), sticks) == ME  # type: ignore[arg-type]

    def test_all_tied_is_a_draw(self) -> None:
        sticks = sticks_of({("ALOA", "BARI"): ME, ("BARI", "COCO"): OPP})

        assert decide_winner((3, 3), (1, 1), sticks) is None  # type: ignore[arg-type]

    def test_the_total_beats_a_better_third_round(self) -> None:
        assert decide_winner((4, 3), (0, 9), tuple(empty_sticks())) == ME


class TestEarlyEnd:
    """A TIE OR ENDING IN BETWEEN: 2・3ラウンド目に杖コマが0本の者がいたら、相手の勝ち。"""

    both = sticks_of({("ALOA", "BARI"): ME, ("BARI", "COCO"): OPP})
    only_opp = sticks_of({("BARI", "COCO"): OPP})
    only_me = sticks_of({("ALOA", "BARI"): ME})

    @pytest.mark.parametrize("round_no", [2, 3])
    def test_player_without_sticks_loses(self, round_no: int) -> None:
        assert early_end_winner(round_no, self.only_opp) == OPP  # type: ignore[arg-type]
        assert early_end_winner(round_no, self.only_me) == ME  # type: ignore[arg-type]

    def test_not_applied_in_the_first_round(self) -> None:
        assert early_end_winner(1, self.only_opp) is None  # type: ignore[arg-type]

    def test_nobody_loses_while_both_have_sticks(self) -> None:
        assert early_end_winner(2, self.both) is None  # type: ignore[arg-type]


class TestLegalMoves:
    def moves(self, state):  # type: ignore[no-untyped-def]
        return RULES.legal_moves(state)

    def test_place_only_on_free_lines_of_the_card_island(self) -> None:
        state = make_state({("ALOA", "BARI"): OPP}, hand=("ALOA",))

        placed = [m for m in self.moves(state) if isinstance(m, PlaceStick)]

        assert {m.line for m in placed} == {line("ALOA", "DUDA"), line("ALOA", "HUNA")}
        assert all(m.card == island("ALOA") for m in placed)

    def test_duplicate_cards_do_not_duplicate_moves(self) -> None:
        state = make_state(hand=("ALOA", "ALOA"))

        placed = [m for m in self.moves(state) if isinstance(m, PlaceStick)]

        assert len(placed) == 3  # ALOA は3本

    def test_no_placing_once_all_twenty_five_sticks_are_on_the_board(self) -> None:
        """25本目までは置け、26本目は置けない(空き点線のある島の札で確かめる)。"""
        free = (line("JOJO", "KAHU"), line("KAHU", "LALE"))  # 末尾の2本だけ空ける
        assert free == (25, 26)
        hand = make_state(hand=("KAHU",))

        def with_my_sticks(count: int):  # type: ignore[no-untyped-def]
            return replace(hand, sticks=tuple(ME if n < count else None for n in range(27)))

        def placements(state) -> list:  # type: ignore[no-untyped-def,type-arg]
            return [m for m in self.moves(state) if isinstance(m, PlaceStick)]

        assert placements(with_my_sticks(24)), "24本目までは置ける"
        assert count_sticks(with_my_sticks(25).sticks, ME) == 25
        assert placements(with_my_sticks(25)) == []

    def test_removal_needs_two_cards_naming_only_the_bridges_islands(self) -> None:
        state = make_state({("ELAI", "FAAA"): OPP}, hand=("ELAI", "FAAA"))

        removals = [m for m in self.moves(state) if isinstance(m, RemoveStick)]

        assert removals == [RemoveStick((island("ELAI"), island("FAAA")), line("ELAI", "FAAA"))]

    def test_one_card_cannot_remove_a_bridge(self) -> None:
        state = make_state({("ELAI", "FAAA"): OPP}, hand=("ELAI",))

        assert not [m for m in self.moves(state) if isinstance(m, RemoveStick)]

    def test_same_island_twice_needs_two_physical_cards(self) -> None:
        one = make_state({("ELAI", "FAAA"): OPP}, hand=("ELAI", "BARI"))
        two = make_state({("ELAI", "FAAA"): OPP}, hand=("ELAI", "ELAI"))

        assert not [m for m in self.moves(one) if isinstance(m, RemoveStick)]
        assert [m for m in self.moves(two) if isinstance(m, RemoveStick)] == [
            RemoveStick((island("ELAI"), island("ELAI")), line("ELAI", "FAAA"))
        ]

    def test_a_card_from_an_unrelated_island_cannot_complete_the_pair(self) -> None:
        state = make_state({("ELAI", "FAAA"): OPP}, hand=("ELAI", "BARI"))

        assert not [m for m in self.moves(state) if isinstance(m, RemoveStick)]

    def test_own_sticks_cannot_be_removed(self) -> None:
        state = make_state({("ELAI", "FAAA"): ME}, hand=("ELAI", "FAAA"))

        assert not [m for m in self.moves(state) if isinstance(m, RemoveStick)]

    def test_identical_removals_are_listed_once(self) -> None:
        state = make_state({("ELAI", "FAAA"): OPP}, hand=("ELAI", "ELAI", "FAAA"))

        removals = [m for m in self.moves(state) if isinstance(m, RemoveStick)]

        assert len(removals) == len(set(removals)) == 2  # (ELAI,ELAI) と (ELAI,FAAA)

    def test_each_distinct_card_can_be_discarded(self) -> None:
        state = make_state(hand=("ALOA", "ALOA", "BARI"))

        discards = [m for m in self.moves(state) if isinstance(m, DiscardCard)]

        assert {m.card for m in discards} == {island("ALOA"), island("BARI")}

    def test_draw_from_each_distinct_market_card_and_the_deck(self) -> None:
        state = make_state(hand=("ALOA",), market=("BARI", "BARI", "COCO"), deck_count=5)

        draws = [m for m in self.moves(state) if isinstance(m, DrawMarket | DrawDeck)]

        assert set(draws) == {
            DrawMarket(island("BARI")),
            DrawMarket(island("COCO")),
            DrawDeck(),
        }

    def test_no_drawing_with_five_cards_in_hand(self) -> None:
        """DRAWING AN ISLAND CARD: 手札が5枚なら、先に1枚以上を捨てる。"""
        state = make_state(
            hand=("ALOA", "BARI", "COCO", "DUDA", "ELAI"), market=("FAAA",), deck_count=5
        )

        assert not [m for m in self.moves(state) if isinstance(m, DrawMarket | DrawDeck)]

    def test_drawing_is_possible_again_after_a_discard(self) -> None:
        state = make_state(
            hand=("ALOA", "BARI", "COCO", "DUDA", "ELAI"), market=("FAAA",), deck_count=5
        )

        after = RULES.apply(state, DiscardCard(island("ALOA")))

        assert DrawMarket(island("FAAA")) in self.moves(after)

    def test_four_cards_can_still_draw(self) -> None:
        state = make_state(hand=("ALOA", "BARI", "COCO", "DUDA"), market=("FAAA",))

        assert DrawMarket(island("FAAA")) in self.moves(state)

    def test_empty_deck_offers_no_deck_draw(self) -> None:
        state = make_state(hand=("ALOA",), market=("FAAA",), deck_count=0)

        assert DrawDeck() not in self.moves(state)

    def test_passing_is_allowed_unless_a_draw_is_forced(self) -> None:
        """DRAWING AN ISLAND CARD: 引かずに終えると、次の手番で相手が必ず引く。"""
        free = make_state(hand=("ALOA",))
        forced = make_state(hand=("ALOA",), must_draw=True)

        assert PassDraw() in self.moves(free)
        assert PassDraw() not in self.moves(forced)

    def test_a_forced_draw_with_nothing_to_draw_can_still_be_ended(self) -> None:
        """引く札が無いのに必ず引くことになっても、手が詰まらない。"""
        state = make_state(hand=("ALOA",), must_draw=True, deck_count=0, market=())

        assert PassDraw() in self.moves(state)

    def test_a_forced_draw_with_cards_available_cannot_be_passed(self) -> None:
        state = make_state(hand=("ALOA",), must_draw=True, deck_count=0, market=("BARI",))

        assert PassDraw() not in self.moves(state)

    def test_apply_unchecked_gives_the_same_result_for_a_legal_move(self) -> None:
        state = make_state(hand=("ALOA", "BARI"))
        move = PlaceStick(island("ALOA"), line("ALOA", "BARI"))

        assert RULES.apply_unchecked(state, move) == RULES.apply(state, move)

    def test_unknown_cards_are_never_played_or_discarded(self) -> None:
        state = replace(make_state(hand=("ALOA",)), hand=(island("ALOA"), UNKNOWN_CARD))

        cards = {m.card for m in self.moves(state) if isinstance(m, PlaceStick | DiscardCard)}

        assert UNKNOWN_CARD not in cards

    def test_no_moves_after_the_game_is_over(self) -> None:
        assert self.moves(make_state(hand=("ALOA",), over=True)) == []

    def test_no_moves_while_the_opponent_is_to_move(self) -> None:
        assert self.moves(make_state(hand=("ALOA",), opponent_to_move=True)) == []


class TestApply:
    def test_placing_uses_the_card_and_puts_the_stick_down(self) -> None:
        state = make_state(hand=("ALOA", "BARI"))

        new = RULES.apply(state, PlaceStick(island("ALOA"), line("ALOA", "BARI")))

        assert new.sticks[line("ALOA", "BARI")] == ME
        assert new.hand == (island("BARI"),)
        assert not new.opponent_to_move  # 手番はまだ続く(0〜5枚使える)

    def test_placing_can_take_control_and_clear_the_opponent(self) -> None:
        state = make_state({("ALOA", "BARI"): ME, ("ALOA", "HUNA"): OPP}, hand=("ALOA",))

        new = RULES.apply(state, PlaceStick(island("ALOA"), line("ALOA", "DUDA")))

        assert new.stones[island("ALOA")] == ME
        assert new.sticks[line("ALOA", "HUNA")] is None

    def test_removing_spends_both_cards(self) -> None:
        state = make_state({("ELAI", "FAAA"): OPP}, hand=("ELAI", "FAAA", "BARI"))

        new = RULES.apply(
            state, RemoveStick((island("ELAI"), island("FAAA")), line("ELAI", "FAAA"))
        )

        assert new.sticks[line("ELAI", "FAAA")] is None
        assert new.hand == (island("BARI"),)

    def test_discard_only_loses_the_card(self) -> None:
        new = RULES.apply(make_state(hand=("ALOA", "BARI")), DiscardCard(island("ALOA")))

        assert new.hand == (island("BARI"),)
        assert not new.opponent_to_move

    def test_drawing_from_the_market_ends_the_turn_and_refills_with_an_unknown(self) -> None:
        state = make_state(hand=("ALOA",), market=("BARI", "COCO", "DUDA"), deck_count=4)

        new = RULES.apply(state, DrawMarket(island("COCO")))

        assert island("COCO") in new.hand
        assert new.market == (island("BARI"), island("DUDA"), UNKNOWN_CARD)
        assert new.deck_count == 3
        assert new.opponent_to_move

    def test_market_is_not_refilled_when_the_deck_is_empty(self) -> None:
        state = make_state(hand=("ALOA",), market=("BARI",), deck_count=0)

        new = RULES.apply(state, DrawMarket(island("BARI")))

        assert new.market == ()
        assert new.deck_count == 0

    def test_drawing_from_the_deck_adds_an_unknown_card(self) -> None:
        new = RULES.apply(make_state(hand=("ALOA",), deck_count=4), DrawDeck())

        assert new.hand == (island("ALOA"), UNKNOWN_CARD)
        assert new.deck_count == 3
        assert new.opponent_to_move

    def test_passing_ends_the_turn_without_drawing(self) -> None:
        state = make_state(hand=("ALOA",), deck_count=4)

        new = RULES.apply(state, PassDraw())

        assert new.opponent_to_move
        assert new.hand == state.hand
        assert new.deck_count == 4

    def test_an_illegal_move_raises(self) -> None:
        state = make_state(hand=("ALOA",))

        with pytest.raises(ValueError, match="合法手ではない"):
            RULES.apply(state, PlaceStick(island("BARI"), line("ALOA", "BARI")))

    def test_apply_does_not_modify_the_state(self) -> None:
        state = make_state(hand=("ALOA",))

        RULES.apply(state, PlaceStick(island("ALOA"), line("ALOA", "BARI")))

        assert state == make_state(hand=("ALOA",))

    def test_removing_the_last_opponent_stick_ends_the_game_from_round_two(self) -> None:
        state = make_state(
            {("ELAI", "FAAA"): OPP, ("ALOA", "BARI"): ME},
            hand=("ELAI", "FAAA"),
            round=2,
        )

        new = RULES_EARLY_END.apply(
            state, RemoveStick((island("ELAI"), island("FAAA")), line("ELAI", "FAAA"))
        )

        assert new.over
        assert new.winner == ME

    def test_no_early_end_in_round_one(self) -> None:
        state = make_state(
            {("ELAI", "FAAA"): OPP, ("ALOA", "BARI"): ME}, hand=("ELAI", "FAAA"), round=1
        )

        new = RULES_EARLY_END.apply(
            state, RemoveStick((island("ELAI"), island("FAAA")), line("ELAI", "FAAA"))
        )

        assert not new.over

    def test_early_end_is_off_by_default(self) -> None:
        """ユーザーの指示: 途中終了は無い。3ラウンドを戦って、合計点で決める。"""
        assert Ruleset().early_end_without_sticks is False
        state = make_state(
            {("ELAI", "FAAA"): OPP, ("ALOA", "BARI"): ME}, hand=("ELAI", "FAAA"), round=3
        )

        new = RULES.apply(
            state, RemoveStick((island("ELAI"), island("FAAA")), line("ELAI", "FAAA"))
        )

        assert not new.over
        assert count_sticks(new.sticks, OPP) == 0  # 相手の杖コマが0本でも続く


class TestNoStoneLimit:
    """カフナコマは1人10個とご確認いただいたが、アプリは11島の支配を認める(実機の最終ラウンドの結果: 0 | 11)。"""

    def test_a_player_can_control_an_eleventh_island(self) -> None:
        stones = empty_stones()
        for name in BOARD.islands[1:11]:  # ALOA 以外の10島を、すでに支配している
            stones[island(name)] = ME
        sticks = sticks_of({("ALOA", "BARI"): ME})

        _, new_stones = place_stick(
            BOARD,
            sticks,
            tuple(stones),
            line("ALOA", "DUDA"),
            ME,  # type: ignore[arg-type]
        )

        assert new_stones[island("ALOA")] == ME

    def test_the_opponents_sticks_are_still_cleared_on_the_eleventh_island(self) -> None:
        stones = empty_stones()
        for name in BOARD.islands[1:11]:
            stones[island(name)] = ME
        sticks = sticks_of({("ALOA", "BARI"): ME, ("ALOA", "HUNA"): OPP})

        new_sticks, _ = place_stick(
            BOARD,
            sticks,
            tuple(stones),
            line("ALOA", "DUDA"),
            ME,  # type: ignore[arg-type]
        )

        assert new_sticks[line("ALOA", "HUNA")] is None


class TestOutcome:
    def over(self, **kwargs):  # type: ignore[no-untyped-def]
        return make_state(over=True, **kwargs)

    def test_none_while_the_game_is_running(self) -> None:
        assert RULES.outcome(make_state(scores=(5, 0))) is None

    @pytest.mark.parametrize(
        ("scores", "expected"),
        [((3, 1), "win"), ((1, 3), "lose")],
    )
    def test_by_total_points(self, scores: tuple[int, int], expected: str) -> None:
        assert RULES.outcome(self.over(scores=scores)) == expected

    def test_tie_goes_to_the_third_round_points(self) -> None:
        assert RULES.outcome(self.over(scores=(3, 3), round3_points=(2, 1))) == "win"

    def test_full_tie_is_a_draw(self) -> None:
        assert RULES.outcome(self.over(scores=(3, 3))) == "draw"

    def test_declared_winner_takes_precedence(self) -> None:
        assert RULES.outcome(self.over(scores=(0, 9), winner=ME)) == "win"

    def test_is_terminal(self) -> None:
        assert RULES.is_terminal(self.over())
        assert not RULES.is_terminal(make_state())


class TestDiff:
    def test_identical_states_have_no_diff(self) -> None:
        state = make_state({("ALOA", "BARI"): ME}, hand=("ALOA",))

        assert RULES.diff(state, state) == {}

    def test_a_missing_stick_is_reported_by_line(self) -> None:
        predicted = make_state({("ALOA", "BARI"): ME})
        actual = make_state()

        assert RULES.diff(predicted, actual) == {"sticks": {line("ALOA", "BARI"): [ME, None]}}

    def test_hand_order_does_not_matter(self) -> None:
        a = make_state(hand=("ALOA", "BARI"))
        b = make_state(hand=("BARI", "ALOA"))

        assert RULES.diff(a, b) == {}

    def test_hand_difference_is_reported(self) -> None:
        diff = RULES.diff(make_state(hand=("ALOA",)), make_state(hand=("BARI",)))

        assert "hand" in diff

    def test_nothing_is_compared_after_my_turn_ends(self) -> None:
        predicted = make_state(opponent_to_move=True)

        assert RULES.diff(predicted, make_state({("ALOA", "BARI"): OPP})) == {}
