"""実機で、土地の所有者を 1 つずつ読む(vision/ownership.py の read_owner を使う)。

読めなかった土地が出たら、そこで止める(後続の操作を送らない)。
入力は adb -s <シリアル> shell input tap のみ。Roll や End Turn は送らない。
"""

import subprocess
import sys
import time
from datetime import datetime

import cv2
import numpy as np

from bglm.core.models import Frame, HoldDrag, InputAction, Tap
from bglm.plugins.monopoly.vision import ownership as ow
from bglm.plugins.monopoly.vision.executor import Driver

SERIAL = "355092380222016"
DONE = {"Electric Company", "Mediterranean Avenue", "Baltic Avenue", "Connecticut Avenue", "Vermont Avenue", "Oriental Avenue"}
PROPS = [p for p in ow.PROPERTY_GROUP if p not in DONE and ow.PROPERTY_GROUP[p] != "light_blue"]


class DeviceIo:
    def capture(self) -> Frame:
        raw = subprocess.run(
            ["adb", "-s", SERIAL, "exec-out", "screencap", "-p"], capture_output=True, check=True
        ).stdout
        image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        return Frame.from_image(image, datetime.now())

    def perform(self, action: InputAction) -> None:
        if isinstance(action, Tap):
            cmd = f"input tap {action.at.x} {action.at.y}"
        elif isinstance(action, HoldDrag):
            raise RuntimeError("このスクリプトでは HoldDrag を送らない")
        else:
            raise RuntimeError(f"未対応の入力: {action}")
        subprocess.run(["adb", "-s", SERIAL, "shell", cmd], check=True)


def main() -> int:
    io = DeviceIo()
    driver = Driver(io=io, sleep=time.sleep)
    for prop in PROPS:
        before = driver.screen()
        reading = ow.read_owner(driver, prop)
        print(f"{prop}\t{reading.owner}\t{reading.reason}\t(開始画面: {before})", flush=True)
        if reading.owner is None:
            print("読めなかったため止める", flush=True)
            return 1
    print("全件完了", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
