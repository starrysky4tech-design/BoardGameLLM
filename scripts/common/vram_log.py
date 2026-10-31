"""GPUメモリ使用量を一定間隔でCSVへ記録する(Phase 0)。

使い方:
    uv run python -m scripts.common.vram_log out.csv --seconds 60 --interval 1
"""

import argparse
import csv
import subprocess
import time
from datetime import datetime
from pathlib import Path

QUERY = "memory.used,memory.total,utilization.gpu"


def sample() -> tuple[int, int, int]:
    """nvidia-smi から (使用MiB, 総MiB, GPU使用率%) を読む。"""
    out = subprocess.run(
        ["nvidia-smi", f"--query-gpu={QUERY}", "--format=csv,noheader,nounits"],
        capture_output=True,
        check=True,
        text=True,
    ).stdout
    used, total, util = (int(v) for v in out.strip().split(","))
    return used, total, util


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out", type=Path)
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--interval", type=float, default=1)
    args = parser.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    peak = 0
    deadline = time.monotonic() + args.seconds
    with args.out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["time", "used_mib", "total_mib", "gpu_util_pct"])
        while time.monotonic() < deadline:
            used, total, util = sample()
            peak = max(peak, used)
            writer.writerow([datetime.now().isoformat(timespec="seconds"), used, total, util])
            f.flush()
            time.sleep(args.interval)
    print(f"最大使用量 {peak} MiB / {total} MiB")


if __name__ == "__main__":
    main()
