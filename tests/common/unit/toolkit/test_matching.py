import numpy as np
import pytest

from bglm.toolkit.matching import NO_MATCH, Match, best_match, correlation, find_peaks, match_score


def _pattern() -> np.ndarray:
    pattern = np.zeros((8, 8), np.uint8)
    pattern[2:6, 1:7] = 255
    pattern[3, 3] = 0
    return pattern


def _scene(*at: tuple[int, int]) -> np.ndarray:
    scene = np.zeros((40, 60), np.uint8)
    for x, y in at:
        scene[y : y + 8, x : x + 8] = _pattern()
    return scene


def test_best_match_finds_the_embedded_template_position() -> None:
    match = best_match(_scene((20, 11)), _pattern())
    assert (match.x, match.y) == (20, 11)
    assert match.score > 0.99


def test_match_score_is_the_maximum_correlation() -> None:
    assert match_score(_scene((5, 5)), _pattern()) == pytest.approx(1.0, abs=1e-4)


def test_template_larger_than_image_gives_no_match() -> None:
    small = np.zeros((4, 4), np.uint8)
    assert best_match(small, _pattern()) == NO_MATCH
    assert match_score(small, _pattern()) == 0.0


def test_correlation_rejects_a_template_larger_than_image() -> None:
    with pytest.raises(ValueError):
        correlation(np.zeros((4, 4), np.uint8), _pattern())


def test_find_peaks_returns_separate_matches_in_descending_order() -> None:
    # Given: 離れた 2 か所に同じ模様
    result = correlation(_scene((4, 4), (40, 25)), _pattern())

    # When
    peaks = find_peaks(result, threshold=0.9, half_width=6, half_height=6)

    # Then: 2 つだけ拾い(山の周りの弱い相関は消える)、高い順
    assert {(p.x, p.y) for p in peaks} == {(4, 4), (40, 25)}
    assert peaks[0].score >= peaks[1].score


def test_find_peaks_merges_matches_within_the_cleared_box() -> None:
    result = correlation(_scene((4, 4), (14, 4)), _pattern())
    wide = find_peaks(result, threshold=0.9, half_width=20, half_height=6)
    assert len(wide) == 1


def test_find_peaks_ignores_scores_below_threshold_and_keeps_input() -> None:
    result = correlation(_scene((4, 4)), _pattern())
    before = result.copy()
    assert find_peaks(result, threshold=1.5, half_width=3, half_height=3) == []
    assert np.array_equal(result, before)


def test_match_is_a_value_object() -> None:
    assert Match(0.5, 1, 2) == Match(0.5, 1, 2)
