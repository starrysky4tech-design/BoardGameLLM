"""手番ごとの同期(plugins/monopoly/sync.py)のテスト。

実機の入出力(Log の読み取り、全体盤の観測、色グループを開く操作)は、偽の関数に差し替える。
全体盤の観測は、台帳と同じ内容から作る(読み取りの正しさは、test_board_scan.py で確かめている)。
"""

from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from bglm.core.models import Frame, InputAction
from bglm.plugins.monopoly import runtime as rt
from bglm.plugins.monopoly import sync
from bglm.plugins.monopoly.logic.catalogue import CATALOGUE
from bglm.plugins.monopoly.logic.decisions import Decider
from bglm.plugins.monopoly.logic.events import (
    AuctionWon,
    DiceRolled,
    LandedOn,
    LogEvent,
    RentPaid,
)
from bglm.plugins.monopoly.logic.log_replay import PositionTracker
from bglm.plugins.monopoly.logic.models import Holding, MonopolyState, Player
from bglm.plugins.monopoly.logic.snapshot import DeedReading
from bglm.plugins.monopoly.vision.board_scan import (
    BoardObservation,
    BoardScan,
    GroupBuildings,
    TileScan,
)
from bglm.plugins.monopoly.vision.cash import CashPair, CashReading
from bglm.plugins.monopoly.vision.dialog_reader import BoxOcr
from bglm.plugins.monopoly.vision.executor import Driver
from bglm.plugins.monopoly.vision.holdings import GroupHouses, HoldingsResult
from bglm.plugins.monopoly.vision.log_reader import LogOcr
from bglm.plugins.monopoly.vision.ownership import Owner

ME, AI = Player.SELF, Player.AI
OWNER = {ME: Owner.ME, AI: Owner.AI, None: Owner.NONE}


class NoIo:
    def capture(self) -> Frame:
        return Frame.from_image(np.zeros((1080, 2432, 3), dtype=np.uint8), datetime(2026, 11, 10))

    def perform(self, action: InputAction) -> None:
        raise AssertionError("同期のテストは、入力を送らない")


def make_agent(holdings: dict[str, Holding], cash: dict[Player, int] | None = None) -> rt.Agent:
    return rt.Agent(
        driver=Driver(io=NoIo(), sleep=lambda _s: None),
        decider=Decider(),
        log_ocr=LogOcr(),
        box_ocr=BoxOcr(),
        positions=PositionTracker({ME: 0, AI: 0}),
        state=MonopolyState(cash=cash or {ME: 500, AI: 500}, holdings=holdings),
    )


def board(
    holdings: dict[str, Holding],
    cash: tuple[int | None, int | None] = (500, 500),
    groups: dict[str, GroupBuildings] | None = None,
    unreadable: tuple[str, ...] = (),
) -> BoardObservation:
    """台帳(holdings)と同じ内容を示す、全体盤の観測。"""
    tiles = {}
    for name in CATALOGUE:
        if name in unreadable:
            tiles[name] = TileScan(None, None)
            continue
        held = holdings.get(name)
        tiles[name] = TileScan(
            OWNER[held.owner if held else None], held.mortgaged if held else False
        )
    return BoardObservation(
        cash=CashPair(
            CashReading(cash[0], 1.0 if cash[0] is not None else 0.0),
            CashReading(cash[1], 1.0 if cash[1] is not None else 0.0),
        ),
        board=BoardScan(tiles=tiles, groups=groups if groups is not None else {}),
        dice=None,
    )


class Script:
    """Synchronizer に渡す偽の入出力。呼ばれた回数を数える。"""

    def __init__(
        self,
        events: list[LogEvent] | None = None,
        gap: bool = False,
        observations: list[BoardObservation] | None = None,
        groups: GroupHouses | None = None,
    ) -> None:
        self.events = events or []
        self.gap = gap
        self.observations = observations or []
        self.group_reads: list[tuple[str, ...]] = []
        self.group_result = groups or GroupHouses()
        self.full_reads = 0
        self.said: list[str] = []
        self.calls = 0

    def read_events(self) -> tuple[list[LogEvent], bool]:
        events, self.events = self.events, []
        return events, self.gap

    def observe(self) -> BoardObservation:
        index = min(self.calls, len(self.observations) - 1)
        self.calls += 1
        return self.observations[index]

    def read_groups(self, groups: tuple[str, ...]) -> GroupHouses:
        self.group_reads.append(groups)
        return self.group_result

    def full_read(self, fallback: dict[str, DeedReading]) -> HoldingsResult:
        self.full_reads += 1
        result = HoldingsResult()
        for name in CATALOGUE:
            result.readings[name] = fallback.get(name, DeedReading(owner=None))
        return result


def synchronizer(agent: rt.Agent, script: Script, resync_limit: int = 4) -> sync.Synchronizer:
    return sync.Synchronizer(
        agent,
        say=script.said.append,
        resync_limit=resync_limit,
        read_events=script.read_events,
        observe=script.observe,
        read_groups=script.read_groups,
        full_read=script.full_read,
    )


# --- 通常の手番 ---


def test_normal_cycle_updates_position_without_opening_anything() -> None:
    holdings = {"Boardwalk": Holding(owner=ME)}
    agent = make_agent(holdings)
    events: list[LogEvent] = [DiceRolled(AI, 3, False), LandedOn(AI, "Baltic Avenue")]
    script = Script(events=events, observations=[board(holdings)])
    assert synchronizer(agent, script).process_log() is False
    assert agent.positions.positions[AI] == 3
    assert script.group_reads == [] and script.full_reads == 0


def test_rent_changes_cash_and_matches_the_screen() -> None:
    holdings = {"Baltic Avenue": Holding(owner=AI)}
    agent = make_agent(holdings)
    events: list[LogEvent] = [RentPaid(ME, 4, AI)]
    script = Script(events=events, observations=[board(holdings, cash=(496, 504))])
    assert synchronizer(agent, script).process_log() is False
    assert dict(agent.state.cash) == {ME: 496, AI: 504}


# --- 金額の読めなかった競り ---


def test_unpriced_auction_is_fixed_without_resync() -> None:
    agent = make_agent({}, cash={ME: 500, AI: 400})
    events: list[LogEvent] = [AuctionWon(AI, "Water Works", None, direct=False)]
    after = {"Water Works": Holding(owner=AI)}
    script = Script(events=events, observations=[board(after, cash=(500, 200))])
    s = synchronizer(agent, script)
    assert s.process_log() is False
    assert s.resyncs == 0 and script.full_reads == 0
    assert agent.state.holdings["Water Works"].owner is AI
    assert dict(agent.state.cash) == {ME: 500, AI: 200}


# --- 所有・抵当の照合 ---


def test_board_owner_change_is_applied_on_the_second_matching_read() -> None:
    agent = make_agent({})
    after = {"Water Works": Holding(owner=AI)}
    script = Script(observations=[board(after), board(after)])
    s = synchronizer(agent, script)
    s.process_log()
    assert "Water Works" not in agent.state.holdings  # 1 回目は保留
    s.process_log()
    assert agent.state.holdings["Water Works"].owner is AI  # 2 回続けて同じ読み


def test_mortgage_flag_is_read_from_the_board() -> None:
    holdings = {"Boardwalk": Holding(owner=ME)}
    agent = make_agent(holdings)
    stamped = {"Boardwalk": Holding(owner=ME, mortgaged=True)}
    script = Script(observations=[board(stamped), board(stamped)])
    s = synchronizer(agent, script)
    s.process_log()
    s.process_log()
    assert agent.state.holdings["Boardwalk"].mortgaged


# --- 家 ---


def red_monopoly(houses: int) -> dict[str, Holding]:
    return {
        n: Holding(owner=ME, houses=houses)
        for n in ("Kentucky Avenue", "Indiana Avenue", "Illinois Avenue")
    }


def test_matching_house_estimate_opens_nothing() -> None:
    holdings = red_monopoly(3)
    agent = make_agent(holdings)
    script = Script(observations=[board(holdings, groups={"red": GroupBuildings(9.1, 0)})])
    synchronizer(agent, script).process_log()
    assert script.group_reads == []


def test_house_mismatch_opens_only_that_group_and_updates_the_ledger() -> None:
    holdings = red_monopoly(1)  # 台帳は 3 軒
    agent = make_agent(holdings)
    found = GroupHouses(houses={"Kentucky Avenue": 3, "Indiana Avenue": 3, "Illinois Avenue": 2})
    script = Script(
        observations=[board(holdings, groups={"red": GroupBuildings(8.0, 0)})], groups=found
    )
    synchronizer(agent, script).process_log()
    assert script.group_reads == [("red",)]
    assert [agent.state.holdings[n].houses for n in sorted(holdings)] == [2, 3, 3]


# --- 再同期 ---


def test_gap_resyncs_with_the_board_only() -> None:
    holdings = {"Boardwalk": Holding(owner=ME)}
    agent = make_agent(holdings)
    after = {**holdings, "Water Works": Holding(owner=AI)}
    script = Script(gap=True, observations=[board(after, cash=(480, 250))])
    s = synchronizer(agent, script)
    assert s.process_log() is False
    assert s.resyncs == 1 and script.full_reads == 0 and script.group_reads == []
    assert agent.state.holdings["Water Works"].owner is AI  # 再同期は、1 回の読みで採る
    assert dict(agent.state.cash) == {ME: 480, AI: 250}


def test_resync_opens_only_monopoly_groups_that_differ() -> None:
    holdings = red_monopoly(0)
    agent = make_agent(holdings)
    found = GroupHouses(houses={n: 4 for n in holdings})
    script = Script(
        gap=True,
        observations=[board(holdings, groups={"red": GroupBuildings(12.0, 0)})],
        groups=found,
    )
    synchronizer(agent, script).process_log()
    assert script.group_reads == [("red",)] and script.full_reads == 0
    assert all(h.houses == 4 for h in agent.state.holdings.values())


def test_resync_falls_back_to_the_full_read_when_a_tile_is_unreadable() -> None:
    holdings = {"Boardwalk": Holding(owner=ME, mortgaged=True)}
    agent = make_agent(holdings)
    script = Script(gap=True, observations=[board(holdings, unreadable=("Park Place",))])
    synchronizer(agent, script).process_log()
    assert script.full_reads == 1
    assert agent.state.holdings["Boardwalk"].mortgaged  # 抵当の旗は、直前の値を引き継ぐ


def test_resync_falls_back_when_the_group_cannot_be_opened() -> None:
    holdings = red_monopoly(0)
    agent = make_agent(holdings)
    script = Script(
        gap=True,
        observations=[board(holdings, groups={"red": GroupBuildings(12.0, 0)})],
        groups=GroupHouses(problems=["red: 盤に戻れない"]),
    )
    synchronizer(agent, script).process_log()
    assert script.full_reads == 1


def test_unreadable_cash_keeps_the_previous_value_on_resync() -> None:
    agent = make_agent({}, cash={ME: 500, AI: 400})
    script = Script(gap=True, observations=[board({}, cash=(450, None))])
    synchronizer(agent, script).process_log()
    assert dict(agent.state.cash) == {ME: 450, AI: 400}


def test_resync_limit_stops_instead_of_looping() -> None:
    agent = make_agent({})
    script = Script(gap=True, observations=[board({})])
    s = synchronizer(agent, script, resync_limit=0)
    assert s.process_log() is True  # 再同期できず、gap のまま → 止める
    assert s.resyncs == 0


def test_incomplete_full_read_raises() -> None:
    agent = make_agent({})
    script = Script(gap=True, observations=[board({}, unreadable=("Park Place",))])

    def broken(_fallback: dict[str, DeedReading]) -> HoldingsResult:
        result = HoldingsResult()
        result.problems.append("盤に戻れない")
        return result

    s = sync.Synchronizer(
        agent,
        say=script.said.append,
        read_events=script.read_events,
        observe=script.observe,
        read_groups=script.read_groups,
        full_read=broken,
    )
    with pytest.raises(sync.SyncError):
        s.process_log()


# --- 保存 ---


def test_session_round_trip(tmp_path: Path) -> None:
    holdings = {"Boardwalk": Holding(owner=ME, houses=2)}
    agent = make_agent(holdings)
    agent.positions.positions[AI] = 17
    path = tmp_path / "session.pkl"
    sync.save_session(path, agent)
    other = make_agent({})
    sync.restore_session(other, sync.load_session(path))
    assert other.state.holdings == holdings
    assert other.positions.positions[AI] == 17


# --- 競りの結果からの学習 ---


def test_my_auction_win_records_that_the_opponent_stopped() -> None:
    agent = make_agent({}, cash={ME: 500, AI: 400})
    events: list[LogEvent] = [AuctionWon(ME, "Kentucky Avenue", 150, direct=False)]
    after = {"Kentucky Avenue": Holding(owner=ME)}
    script = Script(events=events, observations=[board(after, cash=(350, 400))])
    assert synchronizer(agent, script).process_log() is False
    model = agent.decider.bid_model
    assert model.ai_stops == [150 / 220]  # 相手の現金 400 は、落札額 150 を超えていた


def test_an_auction_win_at_the_opponents_exact_cash_is_not_an_observation() -> None:
    agent = make_agent({}, cash={ME: 500, AI: 150})
    events: list[LogEvent] = [AuctionWon(ME, "Kentucky Avenue", 150, direct=False)]
    after = {"Kentucky Avenue": Holding(owner=ME)}
    script = Script(events=events, observations=[board(after, cash=(350, 150))])
    synchronizer(agent, script).process_log()
    assert agent.decider.bid_model.ai_stops == []  # 相手は、上回れなかっただけ


def test_the_opponents_auction_win_records_its_bid() -> None:
    agent = make_agent({}, cash={ME: 500, AI: 400})
    events: list[LogEvent] = [AuctionWon(AI, "Water Works", 140, direct=False)]
    after = {"Water Works": Holding(owner=AI)}
    script = Script(events=events, observations=[board(after, cash=(500, 260))])
    synchronizer(agent, script).process_log()
    assert agent.decider.bid_model.ai_bids == [140 / 150]


def test_the_bid_model_survives_save_and_restore(tmp_path: Path) -> None:
    agent = make_agent({})
    agent.decider.bid_model.record_ai_stop(200, 100, 500)
    path = tmp_path / "session.pkl"
    sync.save_session(path, agent)
    other = make_agent({})
    sync.restore_session(other, sync.load_session(path))
    assert other.decider.bid_model.ai_stops == [0.5]
    assert other.decider.policy.bid_model is other.decider.bid_model  # 方針と共有したまま
