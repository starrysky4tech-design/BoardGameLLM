"""Monopoly の手の型。画面の種類ごとに、合法な手の集合を決める(adapter が使う)。

手は値として表す(不変)。実機での操作(executor)は、この手を入力列に変換する。
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Roll:
    """ダイスを振る(保持してから上へ移動する。RESULT.md)。"""


@dataclass(frozen=True)
class EndTurn:
    pass


@dataclass(frozen=True)
class Buy:
    """止まった土地を買う(Buy → Yes)。"""

    square: str


@dataclass(frozen=True)
class Pass:
    """買わない(Pass → Yes)。オークションに入る。"""

    square: str


@dataclass(frozen=True)
class Bid:
    amount: int


@dataclass(frozen=True)
class Forfeit:
    pass


@dataclass(frozen=True)
class Build:
    square: str


@dataclass(frozen=True)
class Sell:
    square: str


@dataclass(frozen=True)
class Mortgage:
    square: str


@dataclass(frozen=True)
class Unmortgage:
    square: str


@dataclass(frozen=True)
class PostBail:
    pass


@dataclass(frozen=True)
class UseCard:
    pass


@dataclass(frozen=True)
class AcceptTrade:
    pass


@dataclass(frozen=True)
class DeclineTrade:
    pass


Move = (
    Roll
    | EndTurn
    | Buy
    | Pass
    | Bid
    | Forfeit
    | Build
    | Sell
    | Mortgage
    | Unmortgage
    | PostBail
    | UseCard
    | AcceptTrade
    | DeclineTrade
)
