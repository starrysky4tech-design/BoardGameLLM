"""実機で、プラグインの実行ループ(runtime.step / run)を回す。作業用(正式な CLI ではない)。

組み立て: AdbDevice(実機の入出力)、RapidOCR(Log と、購入・オークションの文字)、PositionTracker(位置)、
Decider(方針)。所有の状態(MonopolyState)は、今は空から始める。したがって、所有に依存する判断(購入、建設、
入札の上限)は、実際の状態より保守的・不正確になる。確定操作の画面で止めたいときは --stop-on-decisions を使う。

使い方:
  uv run python run_agent.py --self-pos 0 --ai-pos 29 --max-steps 60 [--stop-on-decisions]
入力: End Turn、Roll、カードを閉じる、Log の開閉とスクロール。--stop-on-decisions なしだと、購入・入札・取引の拒否も送る。
"""

import argparse
import pickle
import time
from dataclasses import replace
from pathlib import Path

from bglm.core.config import AndroidTarget
from bglm.infrastructure.adb_device import AdbDevice
from bglm.plugins.monopoly import runtime as rt
from bglm.plugins.monopoly import sync
from bglm.plugins.monopoly.logic.catalogue import CATALOGUE
from bglm.plugins.monopoly.logic.decisions import Decider
from bglm.plugins.monopoly.logic.log_replay import PositionTracker
from bglm.plugins.monopoly.logic.models import MonopolyState, Player
from bglm.plugins.monopoly.logic.snapshot import DeedReading, build_snapshot
from bglm.plugins.monopoly.vision import executor as ex
from bglm.plugins.monopoly.vision.dialog_reader import BoxOcr
from bglm.plugins.monopoly.vision.holdings import read_all_holdings
from bglm.plugins.monopoly.vision.log_reader import LogOcr

SERIAL = "355092380222016"

parser = argparse.ArgumentParser()
parser.add_argument("--self-pos", type=int, default=None)
parser.add_argument("--ai-pos", type=int, default=None)
parser.add_argument("--self-cash", type=int, default=None)
parser.add_argument("--ai-cash", type=int, default=None)
parser.add_argument("--ai-jail", action="store_true")
parser.add_argument("--self-jail", action="store_true")
parser.add_argument("--max-steps", type=int, default=60)
parser.add_argument("--stop-on-decisions", action="store_true")
parser.add_argument("--read-holdings", action="store_true", help="起動時に、28 か所の所有と家を実機から読み直す")
parser.add_argument("--mortgaged", default="", help="抵当に入っている土地(カンマ区切り。画面から読めないので、Log から渡す)")
parser.add_argument("--from-start", action="store_true", help="対局の開始直後。Log の全行を、開始時の状態(位置 0、現金 1500)から再生する")
parser.add_argument("--auction-square", default="", help="すでに競りの画面のとき、その土地(Log を読めないため、手で渡す)")
parser.add_argument("--set-owner", default="", help="読み落とした所有の手直し(例: \"Ventnor Avenue=ai,Water Works=self\")")
parser.add_argument("--jail-cards", type=int, default=0, help="自分が持つ釈放カードの枚数")
parser.add_argument("--stop-on-trade", action="store_true", help="相手の取引の提案の画面で止める(画面の確認用)")
parser.add_argument("--max-resync", type=int, default=4, help="取りこぼし・現金の食い違いで、自動で再同期する回数の上限")
parser.add_argument("--stop-on-debt", action="store_true", help="負債のメニュー(Auto Sell / Resign)で止める(Resign の確認用)")
parser.add_argument("--resume", action="store_true", help="前回の保存(session.pkl)から再開する。読み直し不要(約 130 秒を省く)")
args = parser.parse_args()
EVENT_LOG = Path(__file__).with_name("events_game3_veryeasy.log")  # 3 局目(Wheelbarrow、Very Easy)の出来事
SESSION = Path(__file__).with_name("session.pkl")  # 作業用の保存。Git 管理外(.gitignore を確認)

device = AdbDevice(AndroidTarget(serial=SERIAL))
driver = ex.Driver(io=device, sleep=time.sleep)
saved = pickle.loads(SESSION.read_bytes()) if args.resume else None
if saved is None and None in (args.self_pos, args.ai_pos, args.self_cash, args.ai_cash):
    raise SystemExit("--resume でないときは、位置と現金の 4 つの引数が要る")
agent = rt.Agent(
    driver=driver,
    decider=Decider(),
    log_ocr=LogOcr(),
    box_ocr=BoxOcr(),
    positions=PositionTracker(
        {Player.SELF: args.self_pos or 0, Player.AI: args.ai_pos or 0},
        in_jail=frozenset(p for p, on in ((Player.AI, args.ai_jail), (Player.SELF, args.self_jail)) if on),
    ),
    state=MonopolyState(cash={Player.SELF: args.self_cash or 0, Player.AI: args.ai_cash or 0}),
    sleep=time.sleep,
    jail_cards=args.jail_cards,
)

if saved is not None:
    sync.restore_session(agent, saved)
    print(f"保存から再開: 位置={dict((p.value, v) for p, v in agent.positions.positions.items())} 現金={dict((p.value, v) for p, v in agent.state.cash.items())}", flush=True)


def save() -> None:
    sync.save_session(SESSION, agent)


def record_events(events) -> None:
    """相手の戦略を調べる材料。全ての出来事を、順に残す。"""
    with EVENT_LOG.open("a", encoding="utf-8") as f:
        for event in events:
            f.write(f"{type(event).__name__} {event}" + chr(10))


synchronizer = sync.Synchronizer(agent, save=save, record=record_events, resync_limit=args.max_resync)


def sync_step() -> bool:
    """盤に戻った後の同期。確認事項があれば True。再同期できなければ、理由を出して終了する(終了コード 5)。"""
    try:
        return synchronizer.process_log()
    except sync.SyncError as error:
        print("    ", error, flush=True)
        raise SystemExit(5) from error


if args.stop_on_debt:
    rt._HANDLERS["board_debt"] = rt._stop("負債のメニュー。--stop-on-debt で止めた(Resign を確認する)")

if args.stop_on_trade:
    rt._HANDLERS["trade"] = rt._stop("取引の提案の画面。--stop-on-trade で止めた")

if args.stop_on_decisions:
    for name in ("buy_dialog", "auction", "trade"):
        rt._HANDLERS[name] = rt._stop(f"{name}: 判断が要る画面。--stop-on-decisions で止めた")

if args.read_holdings and saved is None:
    # 画面から読めない土地は、直前の保存の値で補う(補った土地は表示する)。保存が無ければ、Pennsylvania Railroad だけ
    fallback = {"Pennsylvania Railroad": DeedReading(owner=Player.SELF)}
    if SESSION.exists():
        previous = pickle.loads(SESSION.read_bytes())["state"].holdings
        fallback = {
            name: DeedReading(owner=h.owner, houses=min(h.houses, 4), hotel=h.houses == 5)
            for name, h in previous.items()
        } | fallback
    found = read_all_holdings(driver, fallback=fallback)
    for note in found.assumed:
        print("補った:", note, flush=True)
    if not found.complete:
        print("所有の読み直しが不完全。止める:", found.problems, flush=True)
        print("読めなかった土地:", [n for n in CATALOGUE if found.readings.get(n) is None], flush=True)
        raise SystemExit(5)
    snap = build_snapshot(dict(agent.state.cash), found.readings, CATALOGUE)
    if snap.state is None:
        print("状態を作れない:", snap.reason, flush=True)
        raise SystemExit(5)
    holdings = dict(snap.state.holdings)
    for name in filter(None, (n.strip() for n in args.mortgaged.split(","))):
        holdings[name] = replace(holdings[name], mortgaged=True)
    if SESSION.exists():  # 抵当の旗は、画面から読めない。直前の保存から引き継ぐ
        for name, h in pickle.loads(SESSION.read_bytes())["state"].holdings.items():
            if h.mortgaged and name in holdings and holdings[name].owner is h.owner:
                holdings[name] = replace(holdings[name], mortgaged=True)
    agent.state = MonopolyState(cash=snap.state.cash, holdings=holdings)
    mine = sum(1 for h in holdings.values() if h.owner is Player.SELF)
    print(f"所有を読み直した: 自分 {mine}、Dog {sum(1 for h in holdings.values() if h.owner is Player.AI)}、抵当 {args.mortgaged or '無し'}", flush=True)

# 起点の Log を読み、基準にする(以降は、新しい行だけを取る)
if saved is None and not args.from_start:
    new, gap = rt.read_new_events(agent)
    print(f"起点の Log: {len(new)} 件 gap={gap}", flush=True)
    from bglm.plugins.monopoly.logic.log_replay import last_landed_positions

    derived = last_landed_positions(agent.events)
    for player, pos in derived.items():
        if agent.positions.positions.get(player) != pos:
            print(f"位置を Log から決め直した: {player.value} {agent.positions.positions.get(player)} → {pos}", flush=True)
        agent.positions.positions[player] = pos
    save()

if args.auction_square:
    from bglm.plugins.monopoly.logic.events import AuctionStarted

    agent.events.append(AuctionStarted(Player.SELF, args.auction_square))
    agent.current_auction = args.auction_square

if args.set_owner:
    from bglm.plugins.monopoly.logic.models import Holding

    holdings_fix = dict(agent.state.holdings)
    for pair in filter(None, args.set_owner.split(",")):
        square, who = pair.rsplit("=", 1)
        holdings_fix[square.strip()] = Holding(owner=Player.AI if who.strip() == "ai" else Player.SELF)
        print(f"所有を手直し: {square.strip()} = {who.strip()}", flush=True)
    agent.state = MonopolyState(cash=agent.state.cash, holdings=holdings_fix)

if args.from_start and saved is None:
    if sync_step():
        raise SystemExit(4)

if saved is not None:
    if args.self_pos is not None and args.ai_pos is not None:  # 手で位置を直したいとき(収監の旗も、この指定に従う)
        agent.positions = PositionTracker(
            {Player.SELF: args.self_pos, Player.AI: args.ai_pos},
            frozenset(p for p, on in ((Player.AI, args.ai_jail), (Player.SELF, args.self_jail)) if on),
        )
    if args.self_cash is not None and args.ai_cash is not None:  # 手で現金を直したいとき
        agent.state = MonopolyState(cash={Player.SELF: args.self_cash, Player.AI: args.ai_cash}, holdings=agent.state.holdings)
    if driver.screen() in ("board_my_turn_roll", "board_my_turn_end") and sync_step():
        raise SystemExit(4)

for i in range(args.max_steps):
    result = rt.step(agent)
    print(f"[{i}] {result.outcome.value:8s} 画面={result.screen:20s} {result.action} {result.reason}", flush=True)
    if result.outcome is rt.Outcome.STOPPED:
        break
    if result.outcome is rt.Outcome.WAITED:
        time.sleep(3)
    # Log は約 34 行しか残らないので、盤の通常の画面に戻るたびに読む(カードを閉じた後も)
    if result.action.startswith(("roll", "end_turn", "close_card", "buy", "pass", "bid", "build", "post_bail", "mortgage", "sell_house", "use_jail_card", "accept")):
        time.sleep(4)
        if driver.screen() in ("board_my_turn_roll", "board_my_turn_end") and sync_step():
            break
