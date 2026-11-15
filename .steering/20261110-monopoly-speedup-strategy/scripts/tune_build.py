"""[注意] 旧ルール(build_rule="near"、入口の手前 7 マス)は、2026-11-10 に policies.py から削除した。この結果の再現には、旧ルールの復元が要る。
建設ルールの比較(模擬対戦)。使い方: tune_build.py --games 400

A 側(SELF の席)の勝率を、B(基準)ごとに出す。B は、強欲(GreedyPolicy)と、旧ルール(入口の手前 7 マス)の期待値の方針。
先手は局ごとに交互。乱数の種は固定(再現できる)。
"""
import argparse
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from functools import partial

from bglm.plugins.monopoly.logic.policies import ExpectedValuePolicy, GreedyPolicy
from bglm.plugins.monopoly.logic.simulation import play_match


def make_ev(**kwargs):
    return ExpectedValuePolicy(**kwargs)


def run(job):
    name_a, kwargs_a, name_b, kwargs_b, games, seed = job
    make_b = GreedyPolicy if kwargs_b is None else partial(make_ev, **kwargs_b)
    result = play_match(partial(make_ev, **kwargs_a), make_b, games, seed)
    return name_a, name_b, result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", type=int, default=400)
    parser.add_argument("--seed", type=int, default=1000)
    parser.add_argument("--configs", default="default")
    args = parser.parse_args()
    near = {"build_rule": "near"}
    always = {"build_rule": "near", "build_when_opponent_near": False}
    configs = {"常に建てる": always, "near(旧)": near}
    for r in (0.01, 0.03, 0.05):
        configs[f"return>={r}"] = {"build_rule": "return", "build_min_return": r}
    jobs = []
    for name, kw in configs.items():
        jobs.append((name, kw, "強欲", None, args.games, args.seed))
        jobs.append((name, kw, "常に建てる", always, args.games, args.seed + 5000))
    t = time.time()
    with ProcessPoolExecutor() as pool:
        for name_a, name_b, r in pool.map(run, jobs):
            print(f"{name_a:14} 対 {name_b:8}: 勝率 {r.win_rate_a:.3f} ({r.wins_a}/{r.games}) 平均 {r.average_turns:.0f} 手番 上限決着 {r.decided_by_cap}", flush=True)
    print(f"{time.time()-t:.0f} 秒", file=sys.stderr)


if __name__ == "__main__":
    main()
