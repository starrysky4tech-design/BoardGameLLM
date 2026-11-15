"""Log の出来事から、所持金の増減を計算し、画面の所持金と照合する(画面には依存しない)。

出来事ごとの増減:
- 家賃(RentPaid): 払った側 -N、受け取った側 +N
- カードの現金(MoneyReceived / MoneyLost)
- オークションの落札(AuctionWon、金額のある行だけ): 落札者 -価格
- 税金(LandedOn が Income Tax / Luxury Tax): 止まった側 -税額
- 保釈(BailPosted): -50
- 家の建設(HousesBuilt): -軒数 × 建設費、売却(HousesSold): +軒数 × 建設費 / 2、抵当(Mortgaged): +抵当価値
- GO の給与: 追跡した GO の通過(止まる)回数 × 200(`go_passes`)

台帳に無い増減(購入の行、カードによる移動の給与、取引の現金など)は、予測と画面の所持金の差として現れる。
差が出たら、台帳が足りないか、読み違いがある。呼び出し側が止める。
"""

from collections.abc import Mapping
from dataclasses import dataclass

from bglm.plugins.monopoly.logic.board import BOARD, JAIL_FINE, SquareKind
from bglm.plugins.monopoly.logic.catalogue import CATALOGUE
from bglm.plugins.monopoly.logic.events import (
    AuctionWon,
    BailPosted,
    HotelBuilt,
    HousesBuilt,
    HousesSold,
    LandedOn,
    LogEvent,
    MoneyLost,
    MoneyReceived,
    Mortgaged,
    RentPaid,
    TaxPaid,
    Unmortgaged,
)
from bglm.plugins.monopoly.logic.models import GO_SALARY, Player

BAIL_FEE = JAIL_FINE  # 保釈金。盤の定数と同じ額
_TAX_BY_NAME = {sq.name: sq.amount for sq in BOARD if sq.kind is SquareKind.TAX}


@dataclass(frozen=True)
class CashChange:
    player: Player
    delta: int
    reason: str


def changes_of(events: list[LogEvent], go_passes: Mapping[Player, int]) -> list[CashChange]:
    out: list[CashChange] = []
    for i, event in enumerate(events):
        match event:
            case RentPaid(payer=payer, amount=amount, owner=owner):
                out.append(CashChange(payer, -amount, f"家賃 {amount}"))
                out.append(CashChange(owner, amount, f"家賃 {amount} を受領"))
            case MoneyReceived(player=player, amount=amount, source=source):
                out.append(CashChange(player, amount, f"{source} から受領"))
            case TaxPaid(player=player, amount=amount, tax=tax):
                # 「landed on <税>」が直前にあれば、そちらで数えている。実機で、所得税では「landed on」が出ない
                before = events[i - 1] if i else None
                if not (isinstance(before, LandedOn) and before.player is player):
                    out.append(CashChange(player, -amount, tax))
            case MoneyLost(player=player, amount=amount, source=source):
                out.append(CashChange(player, -amount, f"{source} へ支払い"))
            case AuctionWon(winner=winner, square=square, price=int(price)):
                out.append(CashChange(winner, -price, f"{square} を落札"))
            case LandedOn(player=player, square=square) if square in _TAX_BY_NAME:
                out.append(CashChange(player, -_TAX_BY_NAME[square], f"{square}"))
            case BailPosted(player=player):
                out.append(CashChange(player, -BAIL_FEE, "保釈"))
            case HousesBuilt(player=player, count=count, square=square):
                cost = CATALOGUE[square].house_cost
                out.append(CashChange(player, -count * cost, f"{square} に家 {count} 軒"))
            case HotelBuilt(player=player, square=square):
                out.append(CashChange(player, -CATALOGUE[square].house_cost, f"{square} にホテル"))
            case HousesSold(player=player, count=count, square=square):
                cost = CATALOGUE[square].house_cost
                out.append(CashChange(player, count * cost // 2, f"{square} の家 {count} 軒を売却"))
            case Mortgaged(player=player, square=square, amount=amount):
                out.append(CashChange(player, amount, f"{square} を抵当"))
            case Unmortgaged(player=player, square=square, amount=amount):
                out.append(CashChange(player, -amount, f"{square} の抵当を解除"))
            case _:
                pass
    for player, passes in go_passes.items():
        if passes:
            out.append(CashChange(player, passes * GO_SALARY, f"GO の給与 ×{passes}"))
    return out


def predict(
    cash: Mapping[Player, int], events: list[LogEvent], go_passes: Mapping[Player, int]
) -> dict[Player, int]:
    """いまの所持金に、Log の増減を足した予測。"""
    result = dict(cash)
    for change in changes_of(events, go_passes):
        result[change.player] = result[change.player] + change.delta
    return result


def mismatches(predicted: Mapping[Player, int], observed: Mapping[Player, int | None]) -> list[str]:
    """画面の所持金と合わない項目。読めなかった項目(None)は比べない。"""
    found: list[str] = []
    for player, value in observed.items():
        if value is not None and predicted[player] != value:
            found.append(
                f"{player.value}: 予測 {predicted[player]} 画面 {value}(差 {value - predicted[player]:+d})"
            )
    return found


def reconcile_card_transfers(
    predicted: Mapping[Player, int],
    observed: Mapping[Player, int | None],
    events: list[LogEvent],
) -> tuple[dict[Player, int], list[str]]:
    """カードの「各プレイヤーに払う」の受け取りを、画面の現金で確かめて補う。

    Log には、払う側の「loses M<額> from <カード>」しか出ず、受け取る側の行が無い(実機 2026-11-07:
    Chance で Top Hat が ₼50 を失い、Thimble の現金が +50 になった)。2 人の対局で、払う側の予測が画面と
    一致し、相手の差が払った額とちょうど等しいときだけ、その額を相手に足す。それ以外は補わない。
    """
    fixed = dict(predicted)
    notes: list[str] = []
    for event in events:
        if isinstance(event, MoneyReceived):
            # 逆向き: 「各プレイヤーから受け取る」カード。受け取り側の行だけが出て、払った側の行が無い
            payer = event.player.other()
            seen_payer = observed.get(payer)
            if (
                seen_payer is not None
                and observed.get(event.player) == fixed[event.player]
                and fixed[payer] - seen_payer == event.amount
            ):
                fixed[payer] -= event.amount
                notes.append(
                    f"{event.source}: {event.player.value} の受け取り {event.amount} を相手の支払いとして補った"
                )
            continue
        if not isinstance(event, MoneyLost):
            continue
        other = event.player.other()
        seen = observed.get(other)
        if (
            seen is not None
            and observed.get(event.player) == fixed[event.player]
            and seen - fixed[other] == event.amount
        ):
            fixed[other] += event.amount
            notes.append(
                f"{event.source}: {event.player.value} の支払い {event.amount} を相手の受け取りとして補った"
            )
    return fixed, notes
