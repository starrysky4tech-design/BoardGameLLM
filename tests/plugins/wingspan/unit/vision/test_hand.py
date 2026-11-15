"""手札の配置のテスト。期待値は、実画面で測った左端(4 枚: 442/583/737/889、5 枚: 440/552/665/777/890)。"""

import pytest

from bglm.plugins.wingspan.vision.hand import card_lefts, card_point


def test_four_cards_match_the_measured_lefts() -> None:
    # 274 の手札(ボーナス、ノドアカハチドリ、シロハラミソサザイ、オウゴンアメリカムシクイ): 442 / 583 / 737 / 889
    got = card_lefts(4)
    for measured, computed in zip([442, 583, 737, 889], got, strict=True):
        assert abs(measured - computed) <= 12


def test_five_cards_match_the_measured_lefts() -> None:
    # 297_hand6: 440 / 552 / 665 / 777 / 890
    for measured, computed in zip([440, 552, 665, 777, 890], card_lefts(5), strict=True):
        assert abs(measured - computed) <= 6


def test_ends_are_fixed_regardless_of_the_count() -> None:
    for count in (2, 3, 6, 8):
        lefts = card_lefts(count)
        assert lefts[0] == 442 and lefts[-1] == 890
        assert lefts == sorted(lefts)


def test_press_points_stay_inside_each_visible_strip() -> None:
    for count in (3, 5, 7):
        lefts = card_lefts(count)
        for i in range(count - 1):
            x, _ = card_point(count, i)
            assert lefts[i] < x < lefts[i + 1]  # 次の札に隠れない
        x, _ = card_point(count, count - 1)
        assert x > lefts[-1] + 100  # 右端の札は、中央付近


def test_single_card_and_empty_hand() -> None:
    assert card_lefts(0) == [] and card_lefts(1) == [890]
    with pytest.raises(IndexError):
        card_point(3, 3)
