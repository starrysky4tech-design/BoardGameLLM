"""止まる頻度の集計(scripts/monopoly/landing_frequency.py)の整合性テスト。"""

from scripts.monopoly.landing_frequency import group_report, landing_frequencies

TURNS = 60_000  # 速さを優先した小さい回数。傾向の確認だけを見る


def test_frequencies_sum_to_one_and_go_to_jail_is_never_a_resting_square() -> None:
    freq = landing_frequencies(TURNS, seed=1)
    assert abs(sum(freq) - 1.0) < 1e-9
    assert freq[30] == 0.0  # GO TO JAIL に止まったら、刑務所へ動く


def test_jail_is_the_most_visited_square() -> None:
    freq = landing_frequencies(TURNS, seed=1)
    assert freq.index(max(freq)) == 10


def test_chance_squares_are_visited_less_than_average() -> None:
    # 移動のカードで、別のマスへ動くため
    freq = landing_frequencies(TURNS, seed=1)
    for position in (7, 22, 36):
        assert freq[position] < 0.025


def test_orange_beats_brown_in_return_on_investment() -> None:
    report = {
        group: ratio for group, _income, _cost, ratio in group_report(landing_frequencies(TURNS, 1))
    }
    assert report["orange"] > report["brown"]
    assert report["brown"] == min(report.values())
