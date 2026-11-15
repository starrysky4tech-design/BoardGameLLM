"""実機の所有を読み直し、方針が今建てると判断する家を表示する(入力は、色グループを開く操作だけ。確定は押さない)。"""

import sys
import time
from dataclasses import replace

from bglm.core.config import AndroidTarget
from bglm.infrastructure.adb_device import AdbDevice
from bglm.plugins.monopoly.logic.catalogue import CATALOGUE
from bglm.plugins.monopoly.logic.decisions import Decider, LiveState
from bglm.plugins.monopoly.logic.models import MonopolyState, Player
from bglm.plugins.monopoly.logic.snapshot import DeedReading, build_snapshot
from bglm.plugins.monopoly.vision import executor as ex
from bglm.plugins.monopoly.vision.holdings import read_all_holdings

self_pos, ai_pos, self_cash, ai_cash = map(int, sys.argv[1:5])
mortgaged = [n for n in sys.argv[5].split(",") if n] if len(sys.argv) > 5 else []
driver = ex.Driver(io=AdbDevice(AndroidTarget(serial="355092380222016")), sleep=time.sleep)
found = read_all_holdings(driver, fallback={"Pennsylvania Railroad": DeedReading(owner=Player.SELF)})
assert found.complete, found.problems
snap = build_snapshot({Player.SELF: self_cash, Player.AI: ai_cash}, found.readings, CATALOGUE)
assert snap.state is not None
holdings = dict(snap.state.holdings)
for n in mortgaged:
    holdings[n] = replace(holdings[n], mortgaged=True)
state = MonopolyState(cash=snap.state.cash, holdings=holdings)
for n, h in holdings.items():
    if h.houses:
        print(n, h.owner.value, "houses", h.houses)
live = LiveState(state, {Player.SELF: self_pos, Player.AI: ai_pos})
print("builds:", Decider().builds(live))
