"""実機で、Log を開き → 3 ページ読み → 閉じ、出来事の時系列を表示する。入力は Log の開閉とスクロールのみ。"""
import sys
import time

from bglm.core.config import AndroidTarget
from bglm.infrastructure.adb_device import AdbDevice
from bglm.plugins.monopoly.vision import executor as ex
from bglm.plugins.monopoly.vision.log_reader import LogOcr, read_recent

device = AdbDevice(AndroidTarget(serial="355092380222016"))
driver = ex.Driver(io=device, sleep=time.sleep)
print("画面:", driver.screen(), flush=True)
t = time.time()
reading = read_recent(driver, LogOcr(), pages=int(sys.argv[1]))
print("秒:", round(time.time() - t, 1), "ページ:", reading.pages, reading.reason, flush=True)
for e in reading.events:
    print(" ", e, flush=True)
print("閉じた後の画面:", driver.screen(), flush=True)
