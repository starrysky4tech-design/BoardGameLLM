r"""盤の配置(40 マス)。位置は GO を 0 とし、時計回りに進む。

出典: 盤のキャプチャー(K:\monopoly_img\ボード)と、マスのカード(同\マス)のファイル名の番号。
税金・刑務所・GO の扱いは、ご指示による(.steering/20261101-phase-monopoly/RULES.md)。
"""

from dataclasses import dataclass
from enum import Enum


class SquareKind(Enum):
    GO = "go"
    DEED = "deed"  # 土地・鉄道・会社(name は catalogue のキー)
    CHANCE = "chance"
    COMMUNITY_CHEST = "community_chest"
    TAX = "tax"  # amount を銀行へ払う
    JAIL = "jail"  # 「JUST VISITING」と「IN JAIL」は同じ位置(10)
    FREE_PARKING = "free_parking"
    GO_TO_JAIL = "go_to_jail"


@dataclass(frozen=True)
class Square:
    position: int
    name: str
    kind: SquareKind
    amount: int = 0  # TAX の額


JAIL_POSITION = 10
GO_TO_JAIL_POSITION = 30
JAIL_FINE = 50  # 釈放の罰金(ゾロ目で出るとき、または 3 回休んだ後)
JAIL_MAX_FAILS = 3  # 刑務所で、ゾロ目が出ない失敗の上限(3 回目の失敗で、保釈金を払って出る)
RAILROADS = (5, 15, 25, 35)
UTILITIES = (12, 28)
CHANCE_POSITIONS = (7, 22, 36)
COMMUNITY_CHEST_POSITIONS = (2, 17, 33)

_DEED = SquareKind.DEED

_LAYOUT: tuple[tuple[str, SquareKind, int], ...] = (
    ("GO", SquareKind.GO, 0),  # 0
    ("Mediterranean Avenue", _DEED, 0),  # 1
    ("Community Chest", SquareKind.COMMUNITY_CHEST, 0),  # 2
    ("Baltic Avenue", _DEED, 0),  # 3
    ("Income Tax", SquareKind.TAX, 200),  # 4
    ("Reading Railroad", _DEED, 0),  # 5
    ("Oriental Avenue", _DEED, 0),  # 6
    ("Chance", SquareKind.CHANCE, 0),  # 7
    ("Vermont Avenue", _DEED, 0),  # 8
    ("Connecticut Avenue", _DEED, 0),  # 9
    ("Jail", SquareKind.JAIL, 0),  # 10
    ("St. Charles Place", _DEED, 0),  # 11
    ("Electric Company", _DEED, 0),  # 12
    ("States Avenue", _DEED, 0),  # 13
    ("Virginia Avenue", _DEED, 0),  # 14
    ("Pennsylvania Railroad", _DEED, 0),  # 15
    ("St. James Place", _DEED, 0),  # 16
    ("Community Chest", SquareKind.COMMUNITY_CHEST, 0),  # 17
    ("Tennessee Avenue", _DEED, 0),  # 18
    ("New York Avenue", _DEED, 0),  # 19
    ("Free Parking", SquareKind.FREE_PARKING, 0),  # 20
    ("Kentucky Avenue", _DEED, 0),  # 21
    ("Chance", SquareKind.CHANCE, 0),  # 22
    ("Indiana Avenue", _DEED, 0),  # 23
    ("Illinois Avenue", _DEED, 0),  # 24
    ("B&O Railroad", _DEED, 0),  # 25
    ("Atlantic Avenue", _DEED, 0),  # 26
    ("Ventnor Avenue", _DEED, 0),  # 27
    ("Water Works", _DEED, 0),  # 28
    ("Marvin Gardens", _DEED, 0),  # 29
    ("Go To Jail", SquareKind.GO_TO_JAIL, 0),  # 30
    ("Pacific Avenue", _DEED, 0),  # 31
    ("North Carolina Avenue", _DEED, 0),  # 32
    ("Community Chest", SquareKind.COMMUNITY_CHEST, 0),  # 33
    ("Pennsylvania Avenue", _DEED, 0),  # 34
    ("Short Line", _DEED, 0),  # 35
    ("Chance", SquareKind.CHANCE, 0),  # 36
    ("Park Place", _DEED, 0),  # 37
    ("Luxury Tax", SquareKind.TAX, 100),  # 38
    ("Boardwalk", _DEED, 0),  # 39
)

BOARD: tuple[Square, ...] = tuple(
    Square(position=i, name=name, kind=kind, amount=amount)
    for i, (name, kind, amount) in enumerate(_LAYOUT)
)
BOARD_SIZE = len(BOARD)
POSITION_OF: dict[str, int] = {sq.name: sq.position for sq in BOARD}  # 同名のマスは、最後の位置
DEED_POSITION_OF: dict[str, int] = {
    sq.name: sq.position for sq in BOARD if sq.kind is SquareKind.DEED
}


def next_position(position: int, candidates: tuple[int, ...]) -> int:
    """position から前方(時計回り)で、最初に来る candidates の位置(最寄りの鉄道・会社)。"""
    ahead = [c for c in candidates if c > position]
    return min(ahead) if ahead else min(candidates)
