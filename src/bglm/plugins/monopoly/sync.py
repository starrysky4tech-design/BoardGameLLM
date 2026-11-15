"""手番ごとの同期: Log、所持金、所有・抵当・家を、台帳(`Agent.state`)へ反映し、画面と照合する。

`scripts/run_agent.py` の `process_log` と `resync` を、テストできる形で移した(2026-11-10)。流れ:

1. Log の新しい出来事を読み、位置を追い、所持金を予測する
2. 全体盤の 1 枚(`board_scan.observe`)から、所持金・所有・抵当・家を読む。**タップなし**
3. 予測と画面の所持金を比べる(`logic/cash_check.py`)。金額の読めなかった競りは、現金の差額から逆算する
4. 台帳と全体盤の所有・抵当を照合し、差のある土地だけ直す(`logic/reconcile.py`)。
   家の見積もりが台帳と違う色グループだけ、拡大盤・建設画面を開いて読む
5. 直せない食い違い(取りこぼし、大きな現金の差)だけ、再同期する。再同期も、全体盤 1 枚 + 独占の色だけを開く
   (以前は、8 色すべての拡大盤を巡回して約 130 秒)。全体盤で読めない土地があるときだけ、全部を読み直す

実機の入出力は、`Agent.driver` と、注入できる関数(`read_events`、`observe`、`read_groups`、`full_read`)。
テストでは、これらを偽物に差し替える。
"""

import pickle
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from bglm.plugins.monopoly import runtime as rt
from bglm.plugins.monopoly.logic.cash_check import infer_unpriced_auction, judge_cash
from bglm.plugins.monopoly.logic.catalogue import CATALOGUE
from bglm.plugins.monopoly.logic.events import AuctionWon, LogEvent
from bglm.plugins.monopoly.logic.ledger import predict, reconcile_card_transfers
from bglm.plugins.monopoly.logic.log_replay import PositionTracker, last_landed_positions
from bglm.plugins.monopoly.logic.models import HOTEL_LEVEL, MonopolyState, Player
from bglm.plugins.monopoly.logic.opponent_model import BidModel
from bglm.plugins.monopoly.logic.reconcile import Pending, reconcile, with_houses
from bglm.plugins.monopoly.logic.snapshot import DeedReading, build_snapshot
from bglm.plugins.monopoly.logic.state_update import apply_events
from bglm.plugins.monopoly.vision.board_scan import (
    BoardObservation,
    deed_observations,
    group_observations,
    observe_with_retry,
)
from bglm.plugins.monopoly.vision.holdings import (
    GroupHouses,
    HoldingsResult,
    read_all_holdings,
    read_group_houses,
)


class SyncError(Exception):
    """再同期できない(所有を読めない、状態を作れない)。人が確認する。"""


def _noop() -> None:
    return None


def _noop_record(_events: list[LogEvent]) -> None:
    return None


class Synchronizer:
    def __init__(
        self,
        agent: rt.Agent,
        *,
        save: Callable[[], None] = _noop,
        record: Callable[[list[LogEvent]], None] = _noop_record,
        say: Callable[[str], None] = print,
        resync_limit: int = 4,
        read_events: Callable[[], tuple[list[LogEvent], bool]] | None = None,
        observe: Callable[[], BoardObservation] | None = None,
        read_groups: Callable[[tuple[str, ...]], GroupHouses] | None = None,
        full_read: Callable[[dict[str, DeedReading]], HoldingsResult] | None = None,
    ) -> None:
        self.agent = agent
        self.save = save
        self.record = record
        self.say = say
        self.resync_limit = resync_limit
        self.resyncs = 0
        self.pending: Pending = frozenset()
        self._read_events = read_events or (lambda: rt.read_new_events(agent))
        self._observe = observe or (lambda: observe_with_retry(agent.driver))
        self._read_groups = read_groups or (lambda groups: read_group_houses(agent.driver, groups))
        self._full_read = full_read or (
            lambda fallback: read_all_holdings(agent.driver, fallback=fallback)
        )

    # --- 手番ごとの同期 ---

    def process_log(self) -> bool:
        """盤に戻った後に呼ぶ。位置・現金・所有を更新する。確認事項があれば True(止める)。"""
        agent = self.agent
        new, gap = self._read_events()
        new = rt.own_action_events(new)
        replay = agent.positions.advance(new)
        self.record(new)
        unknown = rt.unknown_lines(new)

        observation = self._observe()
        observed = {Player.SELF: observation.cash.me.value, Player.AI: observation.cash.ai.value}
        deeds = deed_observations(observation.board)

        # 金額の読めなかった競りは、現金の差額から逆算して、金額つきの出来事にする
        predicted = predict(agent.state.cash, new, replay.go_passes)
        board_owner = {n: o.owner for n, o in deeds.items() if o is not None}
        inferred = infer_unpriced_auction(
            new, predicted, observed, agent.state.holdings, board_owner
        )
        if inferred is not None:
            new = [*new, inferred]
            predicted = predict(agent.state.cash, new, replay.go_passes)
            self.say(
                f"    落札の金額を現金の差から逆算した: {inferred.winner.value} が"
                f" {inferred.square} を {inferred.price}"
            )
        predicted, transfer_notes = reconcile_card_transfers(predicted, observed, new)
        for note in transfer_notes:
            self.say(f"    補った: {note}")

        verdict = judge_cash(
            predicted,
            observed,
            new_events=new,
            unknown_lines=unknown,
            gap=gap,
            stopped=bool(replay.stopped),
        )
        self.say(
            f"    Log {len(new)} 件 gap={gap} 未知={unknown}"
            f" 位置={_show(agent.positions.positions)} 補正={replay.corrections} 停止={replay.stopped}"
        )
        self.say(f"    現金 予測={_show(predicted)} 画面={_show(observed)} 差={verdict.diffs}")
        for note in verdict.notes:
            self.say(f"    {note}: {_show(verdict.cash)}")

        if (gap or verdict.diffs) and not replay.stopped and self.resyncs < self.resync_limit:
            self.resync("取りこぼし(gap)" if gap else f"現金の食い違い {verdict.diffs}")
            return False

        self._learn_from_auctions(new, verdict.cash[Player.AI])
        update = apply_events(MonopolyState(cash=verdict.cash, holdings=agent.state.holdings), new)
        agent.state, unresolved = self._reconcile_board(update.state, observation)
        self.save()
        if update.unhandled:
            self.say(f"    状態へ反映できない出来事: {update.unhandled}")
        if unknown:
            self.say(f"    警告: 読めない行(現金・位置の照合は通った): {unknown}")
        if unresolved and self.resyncs < self.resync_limit:
            self.resync(f"全体盤と台帳の食い違い {unresolved}")
            return False
        if replay.stopped and not gap and not verdict.diffs and not update.unhandled and unknown:
            # 読めない行(出目の行など)で位置を追えなかったが、現金は合っている。最後の「landed on」から決め直す
            landed = last_landed_positions(new)
            for player, position in landed.items():
                agent.positions.positions[player] = position
            self.say(f"    位置を Log の「landed on」から決め直した: {_show(landed)}")
            self.save()
            return False
        if gap or replay.stopped or verdict.diffs or update.unhandled:
            self.say("    Log・現金の確認事項があるので止める")
            return True
        return False

    def _learn_from_auctions(self, events: list[LogEvent], ai_cash: int) -> None:
        """競りの結果(金額つき)から、相手の入札の上限の推定(`BidModel`)を更新する。

        自分が落札: 相手の現金が落札額を超えていたなら、相手は上回れたのに降りた(上限の上限の観測)。
        相手が落札: 相手が、その額まで入札した(上限の下限の観測)。
        """
        model = self.agent.decider.bid_model
        for event in events:
            if not isinstance(event, AuctionWon) or event.price is None or event.direct:
                continue
            deed_price = CATALOGUE[event.square].price
            if event.winner is Player.SELF:
                model.record_ai_stop(deed_price, event.price, ai_cash)
            else:
                model.record_ai_bid(deed_price, event.price)

    def _reconcile_board(
        self, state: MonopolyState, observation: BoardObservation
    ) -> tuple[MonopolyState, tuple[str, ...]]:
        """台帳と全体盤を照合する。直した状態と、直せない食い違いを返す。"""
        rec = reconcile(
            state,
            deed_observations(observation.board),
            group_observations(observation.board),
            self.pending,
        )
        self.pending = rec.pending
        for fix in rec.fixes:
            self.say(f"    全体盤に合わせた: {fix}")
        for note in rec.notes:
            self.say(f"    {note}")
        state = rec.state
        if rec.open_groups:
            state = self._open_groups(state, rec.open_groups)
        return state, rec.unresolved

    def _open_groups(self, state: MonopolyState, groups: tuple[str, ...]) -> MonopolyState:
        found = self._read_groups(groups)
        if not found.complete:
            self.say(f"    色グループを読めなかった: {found.problems}")
            return state
        before = {n: h.houses for n, h in state.holdings.items() if n in found.houses}
        updated = with_houses(state, found.houses)
        after = {n: h.houses for n, h in updated.holdings.items() if n in found.houses}
        self.say(f"    {groups} を開いて、家を読み直した: {before} → {after}")
        return updated

    # --- 再同期 ---

    def resync(self, reason: str) -> None:
        """取りこぼし・現金の食い違いのとき、状態を実機から作り直す。

        全体盤 1 枚で、所有・抵当・現金を読む。家は、台帳と食い違う独占の色グループだけ開く。全体盤で読めない土地が
        あるときだけ、全 28 か所を読み直す(約 130 秒)。位置は、Log に残る最後の「landed on」。
        """
        agent = self.agent
        self.resyncs += 1
        self.say(f"    再同期({self.resyncs}/{self.resync_limit}): {reason}")
        observation = self._observe()
        old = agent.state
        cash = {
            Player.SELF: _pick(observation.cash.me.value, old.cash[Player.SELF]),
            Player.AI: _pick(observation.cash.ai.value, old.cash[Player.AI]),
        }
        state = self._rebuild(MonopolyState(cash=cash, holdings=old.holdings), observation)
        agent.state = state
        self.pending = frozenset()
        # 画面の現金は、いまの Log の行まで反映済み。Log を読んで、読み取り位置を進める(同じ行を、もう一度数えない)
        new, _gap = self._read_events()
        landed = last_landed_positions([*agent.events[-60:], *new])
        for player, position in landed.items():
            agent.positions.positions[player] = position
        self.save()
        mine = sum(1 for h in state.holdings.values() if h.owner is Player.SELF)
        self.say(
            f"    再同期した: 位置={_show(agent.positions.positions)}"
            f" 現金={_show(cash)} 自分の所有 {mine}"
        )

    def _rebuild(self, state: MonopolyState, observation: BoardObservation) -> MonopolyState:
        deeds = deed_observations(observation.board)
        if all(o is not None for o in deeds.values()):
            rec = reconcile(state, deeds, group_observations(observation.board), trusted=True)
            if not rec.unresolved:
                for fix in rec.fixes:
                    self.say(f"    全体盤に合わせた: {fix}")
                rebuilt = rec.state
                if rec.open_groups:
                    found = self._read_groups(rec.open_groups)
                    if found.complete:
                        return with_houses(rebuilt, found.houses)
                    self.say(f"    色グループを読めなかった: {found.problems}。全体を読み直す")
                else:
                    return rebuilt
            else:
                self.say(f"    全体盤と台帳が食い違う: {rec.unresolved}。全体を読み直す")
        else:
            self.say("    全体盤で読めない土地がある。全体を読み直す")
        return self._rebuild_full(state)

    def _rebuild_full(self, state: MonopolyState) -> MonopolyState:
        """28 か所を拡大盤・建設画面から読み直す(約 130 秒)。抵当は、画面で読めないので、直前の値を引き継ぐ。"""
        old = state.holdings
        fallback = {
            name: DeedReading(owner=h.owner, houses=min(h.houses, 4), hotel=h.houses == HOTEL_LEVEL)
            for name, h in old.items()
        }
        found = self._full_read(fallback)
        if not found.complete:
            raise SyncError(f"再同期できない(所有を読めない): {found.problems}")
        snap = build_snapshot(dict(state.cash), found.readings, CATALOGUE)
        if snap.state is None:
            raise SyncError(f"再同期できない(状態を作れない): {snap.reason}")
        holdings = {
            name: replace(h, mortgaged=old[name].mortgaged) if name in old else h
            for name, h in snap.state.holdings.items()
        }
        return MonopolyState(cash=snap.state.cash, holdings=holdings)


def _pick(seen: int | None, fallback: int) -> int:
    return fallback if seen is None else seen


def _show(values: dict[Player, int] | dict[Player, int | None]) -> dict[str, int | None]:
    return {p.value: v for p, v in values.items()}


# --- 保存(作業用。`--resume` で、読み直しなしに再開する) ---


def save_session(path: Path, agent: rt.Agent) -> None:
    path.write_bytes(
        pickle.dumps(
            {
                "state": agent.state,
                "positions": dict(agent.positions.positions),
                "in_jail": set(agent.positions.in_jail),
                "jail_roll": dict(agent.positions.jail_roll),
                "cursor": agent.cursor._last,
                "bid_model": agent.decider.bid_model.to_dict(),
            }
        )
    )


def load_session(path: Path) -> dict[str, object]:
    loaded = pickle.loads(path.read_bytes())
    assert isinstance(loaded, dict)
    return loaded


def restore_session(agent: rt.Agent, saved: dict[str, object]) -> None:
    """保存した状態を、Agent へ戻す。"""
    state = saved["state"]
    assert isinstance(state, MonopolyState)
    agent.state = state
    positions = saved["positions"]
    in_jail = saved["in_jail"]
    jail_roll = saved["jail_roll"]
    assert isinstance(positions, dict) and isinstance(in_jail, set) and isinstance(jail_roll, dict)
    agent.positions = PositionTracker(positions, frozenset(in_jail), jail_roll)
    cursor = saved["cursor"]
    assert isinstance(cursor, list)
    agent.cursor._last = cursor
    bid_model = saved.get("bid_model")  # 古い保存には無い
    if isinstance(bid_model, dict):
        agent.decider.bid_model.__dict__.update(BidModel.from_dict(bid_model).__dict__)
