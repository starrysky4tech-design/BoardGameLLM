"""1 周: End Turn → Dog の手番を待つ → Log(Dog の分)→ arm → roll_with_dice → Log(自分の分)→ 位置の照合。

入力: End Turn、Roll、カードを閉じる、Log の開閉とスクロール。購入・入札・取引・建設は、人が判断する画面で止める。
引数: OUT 自分の位置 Dogの位置 Dogが刑務所か(0/1)
"""
import json, sys, time
import cv2
from bglm.core.config import AndroidTarget
from bglm.infrastructure.adb_device import AdbDevice
from bglm.plugins.monopoly.logic.board import BOARD
from bglm.plugins.monopoly.logic.events import UnknownLine
from bglm.plugins.monopoly.logic.log_replay import replay_log
from bglm.plugins.monopoly.logic.models import Player
from bglm.plugins.monopoly.vision import executor as ex
from bglm.plugins.monopoly.vision.log_reader import LogCursor, LogOcr, read_recent
from bglm.plugins.monopoly.vision.roll_reader import RollWatcher, roll_with_dice

OUT = sys.argv[1]
pos = {Player.SELF: int(sys.argv[2]), Player.AI: int(sys.argv[3])}
jail = frozenset({Player.AI}) if sys.argv[4] == "1" else frozenset()
device = AdbDevice(AndroidTarget(serial="355092380222016"))
driver = ex.Driver(io=device, sleep=time.sleep)
ocr, cursor = LogOcr(), LogCursor()
log = lambda *a: print(*a, flush=True)

def read_log(tag):
    r = read_recent(driver, ocr, pages=3)
    new, gap = cursor.update(r.events)
    unknown = [e.text for e in r.events if isinstance(e, UnknownLine)]
    log(f"[{tag}] Log {len(r.events)} 行 新規 {len(new)} gap={gap} 未知={unknown} {r.reason}")
    for e in new: log("   +", e)
    return new

# 起点: 現在の Log を読んで基準にする
read_log("起点")
if driver.screen() == "board_my_turn_end":
    log("end_turn:", ex.end_turn(driver).success)
for i in range(60):
    s = driver.screen()
    if s == "board_my_turn_roll": break
    if s == "card_dialog":
        cv2.imwrite(f"{OUT}/card_{int(time.time())}.png", device.capture().image)
        log("カードを閉じる:", ex.close_card(driver).success); continue
    if s in ("auction", "buy_dialog", "trade", "bid_keypad", "jail_dialog"):
        log("人の判断が要る画面。止める:", s); sys.exit(4)
    time.sleep(3)
else:
    log("Roll 表示にならない"); sys.exit(3)
dog_events = read_log("Dog の手番の後")
watcher = RollWatcher(driver)
log("arm:", watcher.arm())
out = roll_with_dice(driver, watcher)
log("roll_with_dice:", out.read.values, "送信", out.sent, out.reason)
# カードやダイアログが出たら、人の判断が要らない限り閉じる
for _ in range(5):
    s = driver.screen()
    if s == "card_dialog":
        cv2.imwrite(f"{OUT}/card_{int(time.time())}.png", device.capture().image)
        log("カードを閉じる:", ex.close_card(driver).success); continue
    break
log("画面:", driver.screen())
my_events = read_log("自分の手番の後") if driver.screen() in ("board_my_turn_roll", "board_my_turn_end") else []
r = replay_log(pos, dog_events + my_events, jail)
for s in r.steps:
    log(f"  {s.player.value:4s} 出目{s.total:2d}{'(ダブル)' if s.doubles else '       '} 計算{s.expected:2d} Log={s.landed} 採用{s.position:2d} {BOARD[s.position].name} {s.note}")
log("位置: 自分", r.positions[Player.SELF], BOARD[r.positions[Player.SELF]].name, "| Dog", r.positions[Player.AI], BOARD[r.positions[Player.AI]].name, "刑務所:", sorted(p.value for p in r.in_jail))
log("補正:", r.corrections, "停止:", r.stopped)
json.dump({"self": r.positions[Player.SELF], "ai": r.positions[Player.AI], "jail": [p.value for p in r.in_jail]}, open(f"{OUT}/state.json", "w"))
