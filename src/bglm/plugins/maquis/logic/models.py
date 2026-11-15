"""Maquis の状態と手の表現。画面にも VLM にも依存しない(docs/04 の logic の規則)。

手は Phase 0 で確定した3種(.steering/20261111-phase-maquis/02_DESIGN.md)。帰還は自動なので手にしない。
未確認の事項(任務の★、士気の下がる条件、捕縛された団員の扱い)は、状態に持たない。持つと推測で埋めることになるため。
"""

from dataclasses import dataclass, field
from enum import Enum

from bglm.plugins.maquis.logic.patrol import PatrolDeck

RESOURCE_CAP = 4  # アプリ内ルール「資材」: 各4個まで
MORALE_CAP = 7  # 士気のみ7個まで
START_AGENTS = 3  # 普通の難易度の開始人数(実機)
START_RECRUITS = 2  # カフェで勧誘できる人数(実機: 小さな写真が 2人 → 1人 → 0人と減る。2026-11-15 に3回目の勧誘ができないことを確認)
START_MORALE = 6  # 実機の開始時の表示(丸6個)。難易度による違いは未確認


class Phase(Enum):
    PLACEMENT = "placement"  # 配置フェイズ(画面のアイコン: 自転車)
    ACTION = "action"  # 行動フェイズ(画面のアイコン: 旗)


@dataclass(frozen=True)
class Resources:
    morale: int = START_MORALE
    food: int = 0
    medicine: int = 0
    funds: int = 0
    intel: int = 0
    guns: int = 0
    explosives: int = 0

    def get(self, name: str) -> int:
        return int(getattr(self, name))

    def with_delta(self, delta: dict[str, int]) -> "Resources":
        """資材を増減する。上限を超えた分は失われる。負になる減算は呼び出し側が防ぐ。"""
        values = {name: self.get(name) for name in self.__dataclass_fields__}
        for name, change in delta.items():
            cap = MORALE_CAP if name == "morale" else RESOURCE_CAP
            values[name] = min(cap, values[name] + change)
        return Resources(**values)

    def can_pay(self, cost: dict[str, int]) -> bool:
        return all(self.get(name) >= n for name, n in cost.items())


@dataclass(frozen=True)
class Place:
    """団員を1人、地点へ送る。画面では地点をタップ → 右列の1枠目。"""

    location: str


@dataclass(frozen=True)
class Resolve:
    """置いた団員の行動を1つ実行する。画面では地点をタップ → 右列の `slot` 枠(0始まり)。"""

    location: str
    slot: int


@dataclass(frozen=True)
class EndPhase:
    """フェイズ(行動フェイズではターン)を終える。配置は全団員を置いた後だけ。"""


MaquisMove = Place | Resolve | EndPhase


@dataclass(frozen=True)
class MaquisState:
    """Maquis の盤面。任務の勝敗の条件(★がいくつで達成か)は含めない(未確認)。

    `agents`: 地図上の団員のいる枠(地点、または任務の枠 `mission_a` / `mission_b`。1枠に1人まで。昇順)。
    `acted`: 今ターン行動を済ませた団員の枠。
    団員の数 `agents_total` は、実機のターン開始時の `N/M` の M(使える団員。カフェの勧誘で増え、捕縛で減る)。
    捕縛された団員は監獄に入り(`prisoners`)、次のターンも戻らない(実機で確認、2026-11-11)。戻る条件は未確認。
    """

    turn: int = 1
    phase: Phase = Phase.PLACEMENT
    agents_total: int = START_AGENTS
    unplaced: int = START_AGENTS
    prisoners: int = 0
    agents: tuple[str, ...] = ()
    acted: frozenset[str] = frozenset()
    patrols: frozenset[str] = frozenset()
    deck: PatrolDeck = field(default_factory=PatrolDeck)
    resources: Resources = field(default_factory=Resources)
    stars: tuple[int, int] = (0, 0)  # 点灯した★の数(任務A、任務B)。ターンをまたいで残る(実機で確認)
    defeated: bool = False  # 全団員の捕縛(実機で確認: 即敗北)
    recruits_left: int = START_RECRUITS  # カフェで、あと何人勧誘できるか(0 なら勧誘の行動は出ない)
