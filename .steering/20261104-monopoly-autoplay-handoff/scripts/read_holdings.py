"""実機で、28 か所の所有と家を読み直し、結果を表示する。入力は、色グループの拡大盤を開く・戻る操作のみ。"""
import time

from bglm.core.config import AndroidTarget
from bglm.infrastructure.adb_device import AdbDevice
from bglm.plugins.monopoly.logic.models import Player
from bglm.plugins.monopoly.logic.snapshot import DeedReading
from bglm.plugins.monopoly.vision import executor as ex
from bglm.plugins.monopoly.vision.holdings import read_all_holdings

driver = ex.Driver(io=AdbDevice(AndroidTarget(serial="355092380222016")), sleep=time.sleep)
t = time.time()
# Pennsylvania Railroad は、今日の取引(2026-11-05)で自分が受け取り、その後の Log に動きが無い
r = read_all_holdings(driver, fallback={"Pennsylvania Railroad": DeedReading(owner=Player.SELF)})
print("秒:", round(time.time() - t, 1), "完全:", r.complete, "画面:", driver.screen(), flush=True)
for a in r.assumed:
    print("補った:", a, flush=True)
for p in r.problems:
    print("問題:", p, flush=True)
for name, reading in sorted(r.readings.items()):
    print(f"  {name:24s}", None if reading is None else (reading.owner.value if reading.owner else "none", reading.houses, reading.hotel), flush=True)
print("読めた:", len(r.readings), "/ 28", flush=True)
