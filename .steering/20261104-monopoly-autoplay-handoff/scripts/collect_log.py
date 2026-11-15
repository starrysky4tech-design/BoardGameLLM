"""Log を開き、N ページ遡って、OCR の行(重複を除く)を、出現順に scratchpad/log_lines.txt へ書く。入力は Log の開閉とスクロールのみ。"""
import sys, time
import cv2
from bglm.core.config import AndroidTarget
from bglm.core.models import Tap
from bglm.infrastructure.adb_device import AdbDevice
from bglm.plugins.monopoly.vision import executor as ex
from bglm.plugins.monopoly.vision.log_reader import LOG_BUTTON, LOG_CLOSE, SCROLL_UP, LogOcr

N, OUT = int(sys.argv[1]), sys.argv[2]
device = AdbDevice(AndroidTarget(serial="355092380222016"))
driver = ex.Driver(io=device, sleep=time.sleep)
ocr = LogOcr()
assert driver.screen() in ("board_my_turn_roll", "board_my_turn_end"), driver.screen()
device.perform(Tap(LOG_BUTTON)); time.sleep(2.5)
assert driver.screen() == "log", driver.screen()
seen, stale = [], 0
for k in range(N):
    new = 0
    for ln in ocr.read(device.capture().image):
        key = (ln.text,)
        if ln.text not in seen:
            seen.append(ln.text); new += 1
    stale = stale + 1 if new == 0 else 0
    if stale >= 3:
        print("これ以上遡れない(3 ページ連続で新しい行なし)。ページ", k, flush=True); break
    device.perform(SCROLL_UP); time.sleep(1.2)
device.perform(Tap(LOG_CLOSE)); time.sleep(2)
open(OUT, "w", encoding="utf-8").write("\n".join(seen))
print("行数:", len(seen), "閉じた後:", driver.screen(), flush=True)
