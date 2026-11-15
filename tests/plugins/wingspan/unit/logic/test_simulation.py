"""自己対戦の単体テスト。無作為の方針で 1 ゲームを完走できること、不変条件が保たれることを確かめる。"""

import pytest

from bglm.plugins.wingspan.logic.rules import WingspanRules
from bglm.plugins.wingspan.logic.simulation import play_game


@pytest.mark.parametrize("seed", range(20))
def test_random_game_completes_without_breaking_invariants(seed: int) -> None:
    result = play_game(seed)
    assert result.final.terminal
    assert result.final.round_index == 4
    # R p.5: 4 ラウンドで、全員がキューブを使い切って終わる
    assert all(b.cubes == 0 for b in result.final.players)
    assert all(len(b.goal_points) == 4 for b in result.final.players)  # 4 ラウンドぶんの目的の点
    assert result.steps > 26 * 2  # 26 手番 × 2 人 + 各手番の途中の決定


def test_same_seed_gives_same_game() -> None:
    # apply は純粋(乱数は state.seed から決まる)なので、同じ種なら同じ結果になる
    a, b = play_game(7), play_game(7)
    assert a.final == b.final
    assert a.scores == b.scores


def test_outcomes_are_consistent_between_perspectives() -> None:
    result = play_game(3)
    o0, o1 = result.outcomes
    pairs = {("win", "lose"), ("lose", "win"), ("draw", "draw")}
    # 同点で餌まで並べば引き分け。そうでなければ片方だけが勝つ(両方が勝つことは無い)
    assert (o0, o1) in pairs


def test_legal_moves_empty_after_game_end() -> None:
    result = play_game(1)
    assert WingspanRules().legal_moves(result.final) == []
