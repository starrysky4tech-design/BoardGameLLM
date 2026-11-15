"""盤の配置とカタログの整合性テスト。転記ミスを、独立した条件(価格の半額、グループの数など)で検出する。

位置の期待値は、ご指示の [00]〜[39] の記述と、盤のキャプチャー(board_01〜08)から作った。
"""

from collections import Counter

from bglm.plugins.monopoly.logic.board import (
    BOARD,
    CHANCE_POSITIONS,
    COMMUNITY_CHEST_POSITIONS,
    RAILROADS,
    UTILITIES,
    SquareKind,
    next_position,
)
from bglm.plugins.monopoly.logic.catalogue import CATALOGUE, DEEDS
from bglm.plugins.monopoly.logic.models import DeedKind


def test_board_has_40_squares_in_order() -> None:
    assert len(BOARD) == 40
    assert [s.position for s in BOARD] == list(range(40))


def test_special_squares_are_at_the_positions_given_by_the_user() -> None:
    kinds = {s.position: s.kind for s in BOARD}
    assert kinds[0] is SquareKind.GO
    assert kinds[10] is SquareKind.JAIL
    assert kinds[20] is SquareKind.FREE_PARKING
    assert kinds[30] is SquareKind.GO_TO_JAIL
    assert {p for p, k in kinds.items() if k is SquareKind.COMMUNITY_CHEST} == {2, 17, 33}
    assert {p for p, k in kinds.items() if k is SquareKind.CHANCE} == {7, 22, 36}
    assert (BOARD[4].kind, BOARD[4].amount) == (SquareKind.TAX, 200)  # 所得税
    assert (BOARD[38].kind, BOARD[38].amount) == (SquareKind.TAX, 100)  # ラグジュアリー税
    assert CHANCE_POSITIONS == (7, 22, 36)
    assert COMMUNITY_CHEST_POSITIONS == (2, 17, 33)


def test_every_deed_is_on_the_board_exactly_once() -> None:
    on_board = [s.name for s in BOARD if s.kind is SquareKind.DEED]
    assert len(on_board) == 28
    assert Counter(on_board) == Counter(d.name for d in DEEDS)


def test_railroads_and_utilities_are_at_the_expected_positions() -> None:
    for position in RAILROADS:
        assert CATALOGUE[BOARD[position].name].kind is DeedKind.RAILROAD
    for position in UTILITIES:
        assert CATALOGUE[BOARD[position].name].kind is DeedKind.UTILITY
    assert len(RAILROADS) == 4 and len(UTILITIES) == 2


def test_group_sizes_match_the_number_of_deeds_in_each_group() -> None:
    counts = Counter(d.group for d in DEEDS)
    for deed in DEEDS:
        assert counts[deed.group] == deed.group_size, deed.name
    assert counts["brown"] == 2 and counts["dark_blue"] == 2
    assert counts["railroad"] == 4 and counts["utility"] == 2
    assert sum(1 for g, n in counts.items() if n == 3) == 6  # 3 軒の色グループは 6 つ


def test_mortgage_is_half_the_price_for_every_deed() -> None:
    # カードの記載(抵当価値)が、価格の半額になっていること。転記ミスの検出
    for deed in DEEDS:
        assert deed.mortgage * 2 == deed.price, deed.name


def test_rent_tables_increase_with_houses() -> None:
    for deed in DEEDS:
        if deed.kind is DeedKind.STREET:
            assert list(deed.rent) == sorted(deed.rent), deed.name
            assert len(set(deed.rent)) == 6, deed.name


def test_house_cost_follows_the_side_of_the_board() -> None:
    # 辺ごとに価格帯が異なる: 1〜10 は 50、11〜20 は 100、21〜30 は 150、31〜39 は 200
    expected = {range(1, 10): 50, range(11, 20): 100, range(21, 30): 150, range(31, 40): 200}
    for square in BOARD:
        if square.kind is not SquareKind.DEED:
            continue
        deed = CATALOGUE[square.name]
        if deed.kind is not DeedKind.STREET:
            continue
        for positions, cost in expected.items():
            if square.position in positions:
                assert deed.house_cost == cost, deed.name


def test_cards_seen_on_the_screen_match_the_catalogue() -> None:
    assert CATALOGUE["New York Avenue"].rent[2] == 220  # カードの記載(家 2 軒)
    assert CATALOGUE["Indiana Avenue"].rent[0] == 18  # AI に払った額
    assert CATALOGUE["Pacific Avenue"].rent[0] == 26  # AI に払った額
    assert CATALOGUE["Park Place"].rent[0] == 35  # AI が払った額
    assert CATALOGUE["Kentucky Avenue"].mortgage == 110  # 抵当の画面


def test_nearest_railroad_and_utility() -> None:
    assert next_position(7, RAILROADS) == 15
    assert next_position(36, RAILROADS) == 5  # 一周して Reading
    assert next_position(22, UTILITIES) == 28
    assert next_position(36, UTILITIES) == 12
