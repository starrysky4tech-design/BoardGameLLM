"""終局後の後始末: 終局の画面から「メニュー」を押し、「ゲームをセーブして保護区の記録をしますか?」で × を押す(保存しない)。

使い方: uv run python -m scripts.wingspan.finish_game [--save]
- 画面が終局(dialog:final)でなければ、何も押さない
- 既定は保存しない(RESULT.md §10: × (1416,700))。--save は、保存の位置が未測定のため未対応(押さずに止まる)
繰り返しの自動対局で、保護区の記録を残すかは、ユーザーと決める(docs 01 の前提)。
"""

import argparse
import sys
import time

from bglm.core.config import AndroidTarget
from bglm.infrastructure.adb_device import AdbDevice
from bglm.plugins.wingspan.vision.executor import press
from bglm.plugins.wingspan.vision.recognizer import WingspanRecognizer

SERIAL = "355092380222016"
MENU = (687, 985)
DECLINE_SAVE = (1416, 700)
WAIT_SEC = 20.0


def wait_for(rec: WingspanRecognizer, io: AdbDevice, name: str) -> bool:
    deadline = time.monotonic() + WAIT_SEC
    while time.monotonic() < deadline:
        if rec.screen_name(io.capture().image) == name:
            return True
        time.sleep(1.0)
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--save", action="store_true", help="保存する(未対応)")
    args = parser.parse_args()
    if args.save:
        print("--save は未対応(保存の位置が未測定)。押さずに止まる")
        return 2
    io = AdbDevice(AndroidTarget(serial=SERIAL))
    rec = WingspanRecognizer()
    if not wait_for(rec, io, "dialog:final"):
        print("終局の画面(dialog:final)ではない。何も押さない")
        return 1
    io.perform(press(*MENU))
    if not wait_for(rec, io, "dialog:save_prompt"):
        print("保存の確認が出ない。止まる")
        return 1
    io.perform(press(*DECLINE_SAVE))
    time.sleep(6.0)
    print("保存せずにメニューへ戻した。画面:", rec.screen_name(io.capture().image))
    return 0


if __name__ == "__main__":
    sys.exit(main())
