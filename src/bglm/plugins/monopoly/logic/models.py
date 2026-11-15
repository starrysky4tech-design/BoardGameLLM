"""Monopoly の状態と、土地・鉄道・会社の定義(仕様の正本は .steering/20261101-phase-monopoly/LOGIC_SPEC.md)。

金額は、ゲーム内の通貨(M)の整数。状態は不変で、操作は新しい状態を返す。
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum

GO_SALARY = 200  # GO を通過する、または止まると受け取る額
HOTEL_LEVEL = 5  # Holding.houses の値。1〜4 は家、5 はホテル


class Player(Enum):
    SELF = "self"  # 自分(Battleship)
    AI = "ai"  # 相手(Wheelbarrow)

    def other(self) -> "Player":
        return Player.AI if self is Player.SELF else Player.SELF


class DeedKind(Enum):
    STREET = "street"
    RAILROAD = "railroad"
    UTILITY = "utility"


_RENT_LENGTH = {DeedKind.STREET: 6, DeedKind.RAILROAD: 4, DeedKind.UTILITY: 0}


@dataclass(frozen=True)
class Deed:
    """土地・鉄道・会社の定義。値はカードの記載か、画面で確かめた値。

    rent の並び:
    - STREET: (基本賃料, 家1, 家2, 家3, 家4, ホテル) の 6 要素
    - RAILROAD: (所有数1, 2, 3, 4) の 4 要素
    - UTILITY: 空。賃料は、サイコロの目と所有数で決まる
    """

    name: str
    kind: DeedKind
    group: str  # 色のグループ(STREET)。鉄道は "railroad"、会社は "utility"
    group_size: int  # グループの土地の数
    price: int
    mortgage: int  # 抵当価値(抵当に入れると受け取る額)
    rent: tuple[int, ...] = ()
    house_cost: int = 0

    def __post_init__(self) -> None:
        expected = _RENT_LENGTH[self.kind]
        if len(self.rent) != expected:
            raise ValueError(f"{self.name}: rent は {expected} 要素が必要({len(self.rent)} 個)")


@dataclass(frozen=True)
class Holding:
    """所有状態。houses は 0〜4 が家、5(HOTEL_LEVEL)がホテル。"""

    owner: Player
    houses: int = 0
    mortgaged: bool = False

    def __post_init__(self) -> None:
        if not 0 <= self.houses <= HOTEL_LEVEL:
            raise ValueError(f"houses は 0〜{HOTEL_LEVEL}: {self.houses}")


@dataclass(frozen=True)
class MonopolyState:
    cash: Mapping[Player, int]
    holdings: Mapping[str, Holding] = field(default_factory=dict)


@dataclass(frozen=True)
class Trade:
    """取引の提案。proposer が proposer_deeds と proposer_cash を渡し、相手(partner)が
    partner_deeds と partner_cash を渡す。実機の取引画面と同じく、土地と現金の交換。"""

    proposer_deeds: frozenset[str] = frozenset()
    proposer_cash: int = 0
    partner_deeds: frozenset[str] = frozenset()
    partner_cash: int = 0

    def is_empty(self) -> bool:
        return not (
            self.proposer_deeds or self.partner_deeds or self.proposer_cash or self.partner_cash
        )
