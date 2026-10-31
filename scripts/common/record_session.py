"""人が遊んでいる間、端末の画面を記録する(認識の素材集め。ゲームを問わない)。

画面が変わったときだけ保存する。操作は一切送らない(ゲームの状態を変えない)。

使い方:
    uv run python -m scripts.common.record_session --serial <serial> --out datasets/raw/<game>/session1
停止: 出力フォルダに STOP という名前のファイルを作る、または --minutes が経つまで待つ。
"""

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

from bglm.core.config import AndroidTarget
from bglm.core.errors import SourceLostError
from bglm.core.models import Frame
from bglm.infrastructure.adb_device import AdbDevice
from bglm.infrastructure.change_detector import PixelRatioDetector
from bglm.infrastructure.run_logger import write_png


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--interval", type=float, default=1.5, help="取得の間隔(秒)")
    parser.add_argument("--minutes", type=float, default=40.0)
    parser.add_argument("--max-frames", type=int, default=800)
    args = parser.parse_args()

    device = AdbDevice(AndroidTarget(serial=args.serial))
    device.verify()
    detector = PixelRatioDetector()
    args.out.mkdir(parents=True, exist_ok=False)
    stop_file = args.out / "STOP"

    last: Frame | None = None
    saved = 0
    lost = 0
    deadline = time.monotonic() + args.minutes * 60
    print(f"記録開始: {args.out}(止めるには {stop_file} を作る)", flush=True)
    while time.monotonic() < deadline and not stop_file.exists() and saved < args.max_frames:
        try:
            frame = device.capture()
        except SourceLostError as e:
            lost += 1
            print(f"取得に失敗({lost}回目): {e}", flush=True)
            if lost >= 10:
                break
            time.sleep(5)
            continue
        lost = 0
        if last is None or detector.changed(last, frame):
            name = f"f{saved:04d}_{datetime.now():%H%M%S}.png"
            write_png(args.out / name, frame.image)
            saved += 1
            last = frame
            if saved % 20 == 0:
                print(f"{saved}枚保存", flush=True)
        time.sleep(args.interval)
    print(f"記録終了: {saved}枚", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
