"""Wingspan の Phase 0 用: 指定した順にタップし、画面を1枚保存する(原寸と、確認用の縮小)。

使い方: uv run python -m scripts.wingspan.shot NAME [x,y ...] [--wait 1.2] [--scale 0.5]
座標は取得画像(横向き 2432x1080)の座標。タップごとに --wait 秒待つ。
撮影だけのときは座標を渡さない(渡すとタップが送られる)。
"""

import argparse
import subprocess
import time
from pathlib import Path

import cv2
import numpy as np

SERIAL = "355092380222016"  # adb は必ずシリアルを付けて呼ぶ
OUT = Path("datasets/raw/wingspan/feasibility")


def adb(*args: str) -> bytes:
    return subprocess.run(["adb", "-s", SERIAL, *args], check=True, capture_output=True).stdout


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("name")
    parser.add_argument("taps", nargs="*")
    parser.add_argument("--wait", type=float, default=1.2)
    parser.add_argument("--scale", type=float, default=0.5)
    parser.add_argument("--crop", default="", help="x0,y0,x1,y1(確認用の画像だけ切り出す)")
    args = parser.parse_args()

    for tap in args.taps:
        x, y = tap.split(",")
        adb("shell", "input", "tap", x, y)
        time.sleep(args.wait)

    png = adb("exec-out", "screencap", "-p")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{args.name}.png").write_bytes(png)
    image = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise SystemExit("画面を読めなかった(screencap の出力が画像でない)")
    if args.crop:
        x0, y0, x1, y1 = (int(v) for v in args.crop.split(","))
        image = image[y0:y1, x0:x1]
    view = cv2.resize(image, None, fx=args.scale, fy=args.scale, interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(OUT / "_view.png"), view)


if __name__ == "__main__":
    main()
