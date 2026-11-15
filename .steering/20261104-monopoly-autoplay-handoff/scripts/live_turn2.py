"""End Turn → Dog の手番を待つ(カードは閉じる)→ arm → roll_with_dice → take_turn で位置を計算。

位置の計算の起点は、画面で確認した値(引数 start)。入力は End Turn、Roll、カードを閉じる操作のみ。
"""
import sys
import time

import cv2

from bglm.core.config import AndroidTarget
from bglm.infrastructure.adb_device import AdbDevice
from bglm.plugins.monopoly.logic.board import BOARD
from bglm.plugins.monopoly.logic.models import MonopolyState, Player
from bglm.plugins.monopoly.logic.tracker import start
from bglm.plugins.monopoly.logic.turn import take_turn
from bglm.plugins.monopoly.vision import executor as ex
from bglm.plugins.monopoly.vision.roll_reader import RollWatcher, roll_with_dice

OUT, START = sys.argv[1], int(sys.argv[2])
device = AdbDevice(AndroidTarget(serial="355092380222016"))
driver = ex.Driver(io=device, sleep=time.sleep)
log = lambda *a: print(*a, flush=True)

if driver.screen() == "board_my_turn_end":
    r = ex.end_turn(driver)
    log("end_turn:", r.success, r.reason)
for i in range(60):
    s = driver.screen()
    if s == "board_my_turn_roll":
        break
    if s == "card_dialog":
        cv2.imwrite(f"{OUT}/card_{int(time.time())}.png", device.capture().image)
        r = ex.close_card(driver)
        log("カードを閉じる:", r.success, r.reason)
        continue
    if s in ("auction", "buy_dialog", "trade", "bid_keypad", "jail_dialog"):
        log("人の判断が要る画面。止める:", s)
        sys.exit(4)
    log("待機:", i, s)
    time.sleep(3)
else:
    log("Roll 表示にならない。止める")
    sys.exit(3)

watcher = RollWatcher(driver)
log("arm:", watcher.arm(), "before:", watcher.before.values if watcher.before else None)
cv2.imwrite(f"{OUT}/lt2_before.png", device.capture().image)
out = roll_with_dice(driver, watcher)
log("roll_with_dice: values", out.read.values, "total", out.read.total, "doubles", out.read.is_doubles, "sent", out.sent, out.reason, out.read.reason)
cv2.imwrite(f"{OUT}/lt2_after.png", device.capture().image)
if out.read.total:
    t = start(MonopolyState(cash={Player.SELF: 556, Player.AI: 65}), {Player.SELF: START, Player.AI: 10})
    t = take_turn(t, Player.SELF, out.read.total)
    pos = t.positions[Player.SELF]
    log("計算した位置:", pos, BOARD[pos].name, "未確定:", t.unresolved)
