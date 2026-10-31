"""Android端末の画面取得とtapの検証スクリプト(Phase 0)。

使い方:
    uv run python -m scripts.common.adb_capture --serial <serial> capture out.png
    uv run python -m scripts.common.adb_capture --serial <serial> tap 540 1200
    uv run python -m scripts.common.adb_capture --serial <serial> bench 10

シリアルは必須。別の端末を操作する事故を防ぐため、実行のたびに接続中の端末と照合する。
"""

import argparse
import statistics
import subprocess
import sys
import time
from pathlib import Path


def _adb(serial: str, *args: str, timeout: float = 30.0) -> bytes:
    result = subprocess.run(
        ["adb", "-s", serial, *args],
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"adb {' '.join(args)} が失敗: {result.stderr.decode(errors='replace')}")
    return result.stdout


def verify_serial(serial: str) -> None:
    """指定シリアルが接続中の端末に存在することを確かめる。"""
    out = subprocess.run(["adb", "devices"], capture_output=True, check=True).stdout.decode()
    online = [line.split()[0] for line in out.splitlines()[1:] if line.strip().endswith("device")]
    if serial not in online:
        raise SystemExit(f"端末 {serial} が見つからない。接続中: {online}")


def capture(serial: str) -> bytes:
    """画面をPNGで取得する。"""
    return _adb(serial, "exec-out", "screencap", "-p")


def tap(serial: str, x: int, y: int) -> None:
    """端末の物理座標系で tap を送る。"""
    _adb(serial, "shell", "input", "tap", str(x), str(y))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    p_cap = sub.add_parser("capture")
    p_cap.add_argument("out", type=Path)
    p_tap = sub.add_parser("tap")
    p_tap.add_argument("x", type=int)
    p_tap.add_argument("y", type=int)
    p_bench = sub.add_parser("bench")
    p_bench.add_argument("count", type=int)
    args = parser.parse_args()

    verify_serial(args.serial)

    if args.command == "capture":
        started = time.perf_counter()
        data = capture(args.serial)
        elapsed_ms = (time.perf_counter() - started) * 1000
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(data)
        print(f"{args.out} {len(data)}バイト {elapsed_ms:.0f}ms")
    elif args.command == "tap":
        tap(args.serial, args.x, args.y)
        print(f"tap {args.x},{args.y}")
    else:
        times = []
        for _ in range(args.count):
            started = time.perf_counter()
            capture(args.serial)
            times.append((time.perf_counter() - started) * 1000)
        print(
            f"取得{args.count}回: 平均{statistics.mean(times):.0f}ms "
            f"最小{min(times):.0f}ms 最大{max(times):.0f}ms"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
