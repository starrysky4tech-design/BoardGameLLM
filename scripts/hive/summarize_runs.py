"""Hive の実機の対局の記録(runs/*-hive/run.json)を、一覧にして集計する。

使い方:
    uv run python -m scripts.hive.summarize_runs                 # 全部
    uv run python -m scripts.hive.summarize_runs --since 20261031-2  # この ID 以降(文字列の比較)
停止理由の割合を見て、盤が画面に収まらないことで止まる割合(unknown_screen)を測る。
"""

import argparse
import json
from collections import Counter
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--runs", type=Path, default=Path("runs"))
    parser.add_argument("--since", default="", help="この実行ID(の先頭の文字列)以降だけを数える")
    args = parser.parse_args()
    rows = []
    for path in sorted(args.runs.glob("*-hive/run.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["run_id"] < args.since:
            continue
        rows.append(data)
    reasons: Counter[str] = Counter()
    results: Counter[str] = Counter()
    for d in rows:
        reasons[str(d["stop_reason"])] += 1
        if d.get("result"):
            results[str(d["result"])] += 1
        print(
            f"{d['run_id']}  手数 {d['steps']:>3}  停止 {d['stop_reason']:<16}  結果 {d.get('result')}"
        )
    print(f"--- {len(rows)}局")
    print("停止理由:", dict(reasons))
    print("勝敗(こちらから見た結果):", dict(results))


if __name__ == "__main__":
    main()
