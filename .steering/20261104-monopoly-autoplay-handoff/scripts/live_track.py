"""実機の Log を 3 ページ読み、起点の位置から出来事を追って、位置を表示する。入力は Log の開閉とスクロールのみ。"""
import sys
import time

from bglm.core.config import AndroidTarget
from bglm.infrastructure.adb_device import AdbDevice
from bglm.plugins.monopoly.logic.board import BOARD
from bglm.plugins.monopoly.logic.log_replay import replay_log
from bglm.plugins.monopoly.logic.models import Player
from bglm.plugins.monopoly.vision import executor as ex
from bglm.plugins.monopoly.vision.log_reader import LogOcr, read_recent

START_SELF, START_AI = int(sys.argv[1]), int(sys.argv[2])
device = AdbDevice(AndroidTarget(serial="355092380222016"))
driver = ex.Driver(io=device, sleep=time.sleep)
reading = read_recent(driver, LogOcr(), pages=int(sys.argv[3]))
print("ページ:", reading.pages, reading.reason, "出来事:", len(reading.events), flush=True)
r = replay_log({Player.SELF: START_SELF, Player.AI: START_AI}, list(reading.events))
for s in r.steps:
    print(f"  {s.player.value:4s} 出目{s.total:2d}{'(ダブル)' if s.doubles else '       '} 計算{s.expected:2d} Log={s.landed} 採用{s.position:2d} {BOARD[s.position].name} {s.note}", flush=True)
print("位置: 自分", r.positions[Player.SELF], BOARD[r.positions[Player.SELF]].name, "| Dog", r.positions[Player.AI], BOARD[r.positions[Player.AI]].name)
print("食い違い補正:", r.corrections, "停止:", r.stopped, "未知の行:", r.unknown_lines)
