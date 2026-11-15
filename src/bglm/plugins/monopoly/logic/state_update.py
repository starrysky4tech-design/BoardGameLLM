"""Log の出来事を、所有・家・抵当の状態(MonopolyState の holdings)へ反映する(画面には依存しない)。

現金は `ledger.py` が扱う。ここは、所有者・家の数・抵当だけを扱う。
- 落札(金額のある行 `wins … for ₼N`): 落札者の所有にする(金額のない `won … at auction` は、同じ落札の 2 行目)
- 家の建設(`built N houses`): 家を足す(上限は 5 = ホテル)
- 家の売却(`sold N houses`): 家を引く(下限は 0)
- 抵当(`mortgaged`): 抵当の印を付ける

限界(2026-11-07): 起動時のスナップショットは、抵当の状態を読めない(呼び出し側が渡す)。取引で所有が移る行、
抵当の解除、ホテルの扱い(家 4 軒 → ホテル)、購入(自分の購入の Log の行が未確認)は、まだ反映していない。
実機では、この反映を検証できていない(この対局では、すべての土地が所有済みで、Dog の家・抵当が既にある)。
反映できない出来事があれば、`unhandled` に残す。
"""

from dataclasses import dataclass, field, replace

from bglm.plugins.monopoly.logic.catalogue import CATALOGUE
from bglm.plugins.monopoly.logic.events import (
    AuctionWon,
    HotelBuilt,
    HousesBuilt,
    HousesSold,
    LogEvent,
    Mortgaged,
    Unmortgaged,
)
from bglm.plugins.monopoly.logic.models import HOTEL_LEVEL, DeedKind, Holding, MonopolyState


@dataclass(frozen=True)
class StateUpdate:
    state: MonopolyState
    unhandled: list[str] = field(default_factory=list)  # 反映できなかった出来事(矛盾など)


def apply_events(state: MonopolyState, events: list[LogEvent]) -> StateUpdate:
    holdings = dict(state.holdings)
    unhandled: list[str] = []
    for event in events:
        match event:
            case AuctionWon(winner=winner, square=square, price=int()):
                if square in holdings:
                    unhandled.append(f"{square} はすでに所有されているのに、落札の行が出た")
                else:
                    holdings[square] = Holding(owner=winner)
            case HousesBuilt(player=player, count=count, square=square):
                holding = holdings.get(square)
                if holding is None or holding.owner is not player:
                    unhandled.append(f"{square}: 所有者でない {player.value} が家を建てた")
                elif CATALOGUE[square].kind is not DeedKind.STREET:
                    unhandled.append(f"{square}: 街でない土地に家を建てた")
                else:
                    holdings[square] = replace(
                        holding, houses=min(HOTEL_LEVEL, holding.houses + count)
                    )
            case HotelBuilt(player=player, square=square):
                holding = holdings.get(square)
                if holding is None or holding.owner is not player:
                    unhandled.append(f"{square}: 所有者でない {player.value} がホテルを建てた")
                else:
                    holdings[square] = replace(holding, houses=HOTEL_LEVEL)
            case HousesSold(player=player, count=count, square=square):
                holding = holdings.get(square)
                if holding is None or holding.owner is not player:
                    unhandled.append(f"{square}: 所有者でない {player.value} が家を売った")
                else:
                    holdings[square] = replace(holding, houses=max(0, holding.houses - count))
            case Mortgaged(player=player, square=square):
                holding = holdings.get(square)
                if holding is None or holding.owner is not player:
                    unhandled.append(f"{square}: 所有者でない {player.value} が抵当に入れた")
                else:
                    holdings[square] = replace(holding, mortgaged=True)
            case Unmortgaged(player=player, square=square):
                holding = holdings.get(square)
                if holding is None or holding.owner is not player:
                    unhandled.append(f"{square}: 所有者でない {player.value} が抵当を解除した")
                else:
                    holdings[square] = replace(holding, mortgaged=False)
            case _:
                pass
    return StateUpdate(MonopolyState(cash=state.cash, holdings=holdings), unhandled)
