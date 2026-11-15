"""無作為の方針と MaquisStrategy を、固定シードの自己プレイで比べる。

使い方: uv run python -m scripts.maquis.compare_policies [ゲーム数] [標本数]
結果は標準出力に出す(敗北率、平均の到達ターン・団員・資材・★)。
"""

import random
import sys
from dataclasses import replace
from statistics import mean

from bglm.plugins.maquis.logic.simulation import (
    GameResult,
    Policy,
    play_game,
    random_policy,
    strategy_policy,
)
from bglm.plugins.maquis.logic.strategy import MaquisStrategy, load_weights


def run(name: str, make_policy: "type[object] | object", games: int) -> list[GameResult]:
    results: list[GameResult] = []
    for seed in range(games):
        rng = random.Random(1000 + seed)  # 山札の引きは両方の方針で同じ並びから始まる
        policy: Policy = make_policy(seed)  # type: ignore[operator]
        results.append(play_game(policy, rng))
    lost = sum(r.defeated for r in results)
    print(
        f"{name}: 敗北 {lost}/{games}  到達ターン {mean(r.turns for r in results):.2f}  "
        f"団員 {mean(r.agents for r in results):.2f}  資材 {mean(r.resources for r in results):.2f}  "
        f"★ {mean(r.stars for r in results):.2f}  3地点埋まり {sum(r.blocked for r in results)}",
        flush=True,
    )
    return results


def main() -> None:
    games = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    samples = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    run("無作為", lambda seed: random_policy(random.Random(seed)), games)
    weights = replace(load_weights(), samples=samples)
    run(
        f"モンテカルロ(標本{samples})",
        lambda seed: strategy_policy(MaquisStrategy(weights=weights, rng=random.Random(seed))),
        games,
    )


if __name__ == "__main__":
    main()
