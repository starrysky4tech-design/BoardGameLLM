"""Monopoly の方針どうしを自己対戦させて、勝率を測る(戦略の評価用)。

使い方:
    uv run python -m scripts.monopoly.evaluate_strategy --games 400
A 側(SELF の席)の勝率を、基準との組み合わせごとに出す。先手は局ごとに交互にする。
"""

import argparse
from collections.abc import Callable

from bglm.plugins.monopoly.logic.engine import Policy
from bglm.plugins.monopoly.logic.policies import ExpectedValuePolicy, GreedyPolicy
from bglm.plugins.monopoly.logic.simulation import play_match

Factory = Callable[[], Policy]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--games", type=int, default=400)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    matches: list[tuple[str, Factory, str, Factory]] = [
        ("期待値", ExpectedValuePolicy, "強欲(基準)", GreedyPolicy),
        ("強欲(基準)", GreedyPolicy, "強欲(基準)", GreedyPolicy),
        ("期待値", ExpectedValuePolicy, "期待値", ExpectedValuePolicy),
    ]
    for name_a, make_a, name_b, make_b in matches:
        result = play_match(make_a, make_b, args.games, args.seed)
        print(
            f"{name_a} 対 {name_b}: {name_a} の勝率 {result.win_rate_a:.3f} "
            f"({result.wins_a}/{result.games})  平均 {result.average_turns:.0f} 手番  "
            f"上限で決着 {result.decided_by_cap} 局"
        )


if __name__ == "__main__":
    main()
