"""次の手番で各マスに止まる確率(logic/landing_odds.py)のテスト。期待値は、手で計算した分数。"""

from fractions import Fraction

import pytest

from bglm.plugins.monopoly.logic.landing_odds import next_turn_landing


def close(value: float, expected: Fraction) -> bool:
    return abs(value - float(expected)) < 1e-12


def test_distance_two_needs_exactly_double_one() -> None:
    # 2 マス先は、最初の 1 投の (1, 1) だけ(最小の出目が 2 なので、振り直しでは届かない)
    assert close(next_turn_landing(0).at(2), Fraction(1, 36))


def test_distance_three_is_two_of_thirty_six() -> None:
    assert close(next_turn_landing(0).at(3), Fraction(2, 36))


def test_distance_four_adds_the_double_reroll_route() -> None:
    # 最初の 1 投で合計 4(3 通り)。または (1,1) で 2 マス進み、振り直しの (1,1) でもう 2 マス
    expected = Fraction(3, 36) + Fraction(1, 36) * Fraction(1, 36)
    assert close(next_turn_landing(0).at(4), expected)


def test_distance_seven_counts_all_routes() -> None:
    # 最初の 1 投で 7(6 通り、すべてゾロ目でない)
    # (1,1) → 2 の後に 5(4 通り)、(2,2) → 4 の後に 3(2 通り)
    # (1,1) → (1,1) → 4 の後に 3(2 通り。3 投目はゾロ目でない)
    expected = (
        Fraction(6, 36)
        + Fraction(1, 36) * Fraction(4, 36)
        + Fraction(1, 36) * Fraction(2, 36)
        + Fraction(1, 36) * Fraction(1, 36) * Fraction(2, 36)
    )
    assert close(next_turn_landing(0).at(7), expected)


def test_position_wraps_around_the_board() -> None:
    assert close(next_turn_landing(38).at(0), Fraction(1, 36))  # 38 + 2


def test_three_doubles_go_to_jail() -> None:
    odds = next_turn_landing(0)
    assert odds.jail >= float(Fraction(1, 216))
    assert odds.jail < 0.01  # Go To Jail に止まる経路を足しても、小さい


def test_go_to_jail_square_is_never_a_landing() -> None:
    odds = next_turn_landing(24)  # 30 まで 6 マス
    assert odds.at(30) == 0.0
    # 合計 6 の 5 通り((3,3) のゾロ目を含む)で、Go To Jail に止まって刑務所へ行く
    assert odds.jail > float(Fraction(5, 36))


def test_jail_square_itself_is_a_normal_landing() -> None:
    assert next_turn_landing(5).at(10) > 0  # 5 マス先の、見物のマス


def test_in_jail_only_doubles_leave_and_move_by_that_roll() -> None:
    odds = next_turn_landing(0, in_jail=True, jail_failed=0)
    assert sum(odds.land.values()) == pytest.approx(6 / 36)
    for total in (2, 4, 6, 8, 10, 12):  # ゾロ目の合計
        assert close(odds.at((10 + total) % 40), Fraction(1, 36))
    assert odds.at(17) == 0.0  # ゾロ目でない 7 では出られない
    assert odds.jail == 0.0


def test_in_jail_third_failure_pays_bail_and_moves() -> None:
    odds = next_turn_landing(0, in_jail=True, jail_failed=2)
    assert sum(odds.land.values()) + odds.jail == pytest.approx(1.0)  # どの出目でも出る
    assert close(odds.at(17), Fraction(6, 36))  # 7(6 通り)


def test_in_jail_double_that_lands_on_go_to_jail_is_jail() -> None:
    # 刑務所(10)から 20 マスは動けないので、この経路は無い。確率の合計が 1 を超えないことだけ確かめる
    odds = next_turn_landing(0, in_jail=True, jail_failed=2)
    assert sum(odds.land.values()) + odds.jail <= 1.0 + 1e-12


def test_probabilities_stay_in_range() -> None:
    odds = next_turn_landing(7)
    assert all(0 <= p <= 1 for p in odds.land.values())
    assert 0 <= odds.jail <= 1


def test_invalid_arguments_are_rejected() -> None:
    with pytest.raises(ValueError):
        next_turn_landing(40)
    with pytest.raises(ValueError):
        next_turn_landing(0, in_jail=True, jail_failed=3)
