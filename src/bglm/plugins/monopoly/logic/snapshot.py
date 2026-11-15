"""画面から読んだ土地の状態を、対局の状態(MonopolyState)に変える。画面には依存しない(vision を import しない)。

入力は、土地ごとの所有者・家の数・ホテルの有無と、所持金。どれかが読めていない土地があれば、推測せず止める。
所有は Player、無所有は None。ホテルは家 5 軒(HOTEL_LEVEL)として扱う。
"""

from collections.abc import Mapping
from dataclasses import dataclass

from bglm.plugins.monopoly.logic.models import (
    HOTEL_LEVEL,
    Deed,
    DeedKind,
    Holding,
    MonopolyState,
    Player,
)


@dataclass(frozen=True)
class DeedReading:
    owner: Player | None  # None は無所有
    houses: int = 0
    hotel: bool = False


@dataclass(frozen=True)
class SnapshotResult:
    state: MonopolyState | None
    reason: str = ""  # state が None のときの停止理由


def build_snapshot(
    cash: Mapping[Player, int],
    readings: Mapping[str, DeedReading | None],
    catalogue: Mapping[str, Deed],
) -> SnapshotResult:
    """読み取り結果から MonopolyState を作る。読めていない土地(None)や、全部の土地が揃わないときは止める。"""
    missing = sorted(name for name in catalogue if name not in readings)
    if missing:
        return SnapshotResult(None, f"読み取りの無い土地: {missing[:3]}…")
    unreadable = sorted(name for name, reading in readings.items() if reading is None)
    if unreadable:
        return SnapshotResult(None, f"読めなかった土地: {unreadable[:3]}")

    holdings: dict[str, Holding] = {}
    for name, reading in readings.items():
        if name not in catalogue:
            return SnapshotResult(None, f"カタログに無い土地: {name}")
        assert reading is not None  # unreadable は上で弾いた
        if reading.owner is None:
            if reading.houses or reading.hotel:
                return SnapshotResult(None, f"無所有の土地に家がある: {name}")
            continue
        houses = HOTEL_LEVEL if reading.hotel else reading.houses
        if houses and catalogue[name].kind is not DeedKind.STREET:
            return SnapshotResult(None, f"土地でないものに家がある: {name}")
        holdings[name] = Holding(owner=reading.owner, houses=houses)

    state = MonopolyState(cash=dict(cash), holdings=holdings)
    return SnapshotResult(state)
