"""[注意] 旧ルール(build_rule="near"、入口の手前 7 マス)は、2026-11-10 に policies.py から削除した。この結果の再現には、旧ルールの復元が要る。
新ルール(下限 0.01)と旧ルール(near)の直接対戦(作業用)。"""
import sys
from concurrent.futures import ProcessPoolExecutor
from functools import partial
from bglm.plugins.monopoly.logic.policies import ExpectedValuePolicy
from bglm.plugins.monopoly.logic.simulation import play_match

def run(seed_games):
    seed, games = seed_games
    new = partial(ExpectedValuePolicy, build_rule="return", build_min_return=0.01)
    old = partial(ExpectedValuePolicy, build_rule="near")
    r = play_match(new, old, games, seed)
    return r.wins_a, r.games, r.decided_by_cap

if __name__ == "__main__":
    jobs = [(20000 + 100 * i, 100) for i in range(12)]  # 1200 局
    with ProcessPoolExecutor() as pool:
        res = list(pool.map(run, jobs))
    wins = sum(r[0] for r in res); games = sum(r[1] for r in res); cap = sum(r[2] for r in res)
    print(f"新(0.01) 対 旧(near): 新の勝率 {wins/games:.3f} ({wins}/{games}) 上限決着 {cap}")
