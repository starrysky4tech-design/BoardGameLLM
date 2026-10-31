"""board.json(実機で読み取った盤面)の整合性。点線の数は、手札のカード選択で出る照準マークの数で確認した。"""

import json
from collections import Counter

import pytest
from tests.plugins.kahuna.support.helpers import BOARD, island, line

from bglm.plugins.kahuna.logic.models import BOARD_PATH, default_board, load_board

# 実機で数えた点線の本数。ALOA/COCO/ELAI/HUNA は照準マークの数で確認、残りは地図からの読み取り
EXPECTED_DEGREE = {
    "ALOA": 3, "BARI": 5, "COCO": 4, "DUDA": 4, "ELAI": 6, "FAAA": 5,
    "GOLA": 4, "HUNA": 5, "IFFI": 5, "JOJO": 5, "KAHU": 5, "LALE": 3,
}  # fmt: skip


class TestBoardData:
    def test_has_twelve_islands_and_twenty_seven_lines(self) -> None:
        assert len(BOARD.islands) == 12
        assert len(BOARD.lines) == 27

    @pytest.mark.parametrize(("name", "degree"), EXPECTED_DEGREE.items())
    def test_degree_of_each_island(self, name: str, degree: int) -> None:
        assert BOARD.degree(island(name)) == degree

    def test_degrees_sum_to_twice_the_number_of_lines(self) -> None:
        assert sum(BOARD.degree(i) for i in range(12)) == 2 * 27

    def test_every_line_joins_two_different_islands_in_order(self) -> None:
        assert all(0 <= ln.a < ln.b < 12 for ln in BOARD.lines)

    def test_no_two_lines_join_the_same_pair(self) -> None:
        pairs = Counter((ln.a, ln.b) for ln in BOARD.lines)
        assert max(pairs.values()) == 1

    def test_lines_of_lists_exactly_the_lines_touching_each_island(self) -> None:
        for i in range(12):
            touching = {n for n, ln in enumerate(BOARD.lines) if i in (ln.a, ln.b)}
            assert set(BOARD.lines_of[i]) == touching

    def test_every_line_position_is_inside_the_frame(self) -> None:
        data = json.loads(BOARD_PATH.read_text(encoding="utf-8"))
        width, height = data["frame"]["width"], data["frame"]["height"]
        assert all(0 <= ln.position.x < width and 0 <= ln.position.y < height for ln in BOARD.lines)

    def test_line_positions_are_distinct(self) -> None:
        assert len({(ln.position.x, ln.position.y) for ln in BOARD.lines}) == 27

    def test_all_but_one_line_position_is_measured(self) -> None:
        """25本は杖コマの実測、1本は照準マーク、1本(IFFI-KAHU)だけが概算。"""
        sources = Counter(ln.source for ln in BOARD.lines)

        assert sources == {"detected": 25, "verified": 1, "estimated": 1}
        assert [i for i, ln in enumerate(BOARD.lines) if not ln.measured] == [line("IFFI", "KAHU")]

    def test_every_island_has_a_stone_position_inside_the_frame(self) -> None:
        assert len(BOARD.stone_positions) == 12
        assert all(0 <= p.x < 2432 and 0 <= p.y < 1080 for p in BOARD.stone_positions)

    def test_stone_positions_are_far_apart_from_each_other(self) -> None:
        points = BOARD.stone_positions
        nearest = min(
            ((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5
            for i, a in enumerate(points)
            for b in points[i + 1 :]
        )

        assert nearest > 120  # 隣の島の石と取り違えない

    def test_only_the_coco_stone_position_is_an_estimate(self) -> None:
        """COCO は記録したゲームで支配されず、石を観測できなかった。"""
        assert [BOARD.islands[i] for i, ok in enumerate(BOARD.stone_measured) if not ok] == ["COCO"]


class TestLookups:
    def test_line_between_is_order_independent(self) -> None:
        assert BOARD.line_between(island("ELAI"), island("BARI")) == line("BARI", "ELAI")

    def test_line_between_unconnected_islands_raises(self) -> None:
        with pytest.raises(KeyError):
            BOARD.line_between(island("ALOA"), island("LALE"))

    def test_other_end(self) -> None:
        n = line("ALOA", "BARI")

        assert BOARD.other_end(n, island("ALOA")) == island("BARI")
        assert BOARD.other_end(n, island("BARI")) == island("ALOA")

    def test_other_end_of_an_untouched_island_raises(self) -> None:
        with pytest.raises(ValueError):
            BOARD.other_end(line("ALOA", "BARI"), island("LALE"))

    def test_unknown_island_name_raises(self) -> None:
        with pytest.raises(ValueError):
            BOARD.island_index("NOWHERE")


def test_default_board_is_cached_and_equals_a_fresh_load() -> None:
    assert default_board() is default_board()
    assert default_board() == load_board()
