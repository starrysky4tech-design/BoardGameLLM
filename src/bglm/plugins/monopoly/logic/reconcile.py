"""台帳(Log と操作の結果で更新した状態)と、全体盤の読み取りを照合する(画面には依存しない)。

台帳が主で、画面は照合に使う。差が出たとき、全体の読み直し(約 130 秒)ではなく、差のあった土地・色グループだけ直す。

- 所有・抵当: 全体盤の読みが 2 回続けて同じなら採る(駒・演出の重なりによる 1 回の誤読で、台帳を書き換えない)。
  `trusted=True` のとき(再同期で、読み取りを自分で確かめた直後)は、1 回で採る
- 家・ホテル: 全体盤の読みは、色グループ単位の見積もり(±1 軒ほど)。**台帳は書き換えず**、差が大きい色グループを
  「開いて確かめる」として返す。独占でない色グループの家は、ルール上ありえないので、誤読として捨てる
- 直せない食い違い(台帳は所有なのに、全体盤は無所有 など)は `unresolved` に返す。呼び出し側が止める・読み直す

家の軒数を、見積もりで直せない理由は `.steering/20261110-monopoly-speedup-strategy/RESULT.md` を参照。
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace

from bglm.plugins.monopoly.logic.catalogue import CATALOGUE, street_groups
from bglm.plugins.monopoly.logic.models import (
    HOTEL_LEVEL,
    Deed,
    Holding,
    MonopolyState,
    Player,
)

# 家の見積もりと台帳の差が、この軒数以上なら、その色グループを開いて確かめる。
# 見積もりの誤差は ±1 軒ほど(RESULT.md)。1 軒の差は見逃し、現金の照合(家の建設費の差)に任せる
HOUSE_UNITS_TOLERANCE = (
    1.5  # (仮。見積もりの誤差は、3 枚の画像で ±0.1 軒。実機で、4 軒・ホテルの画像を取って見直す)
)

# 保留の差: (土地の名前, 項目("owner" か "mortgaged"), 値)。1 回目の読みを覚え、2 回目に同じなら採る
Pending = frozenset[tuple[str, str, str]]


@dataclass(frozen=True)
class DeedObservation:
    owner: Player | None  # 無所有は None
    mortgaged: bool | None  # 読めなければ None


@dataclass(frozen=True)
class GroupObservation:
    house_units: float  # 家の軒数の見積もり
    hotels: int


@dataclass(frozen=True)
class Reconciliation:
    state: MonopolyState
    pending: Pending  # 次の照合へ引き継ぐ、保留の差
    fixes: tuple[str, ...]  # 台帳を直した内容(記録用)
    open_groups: tuple[str, ...]  # 開いて確かめる色グループ
    unresolved: tuple[str, ...]  # 直せない食い違い
    notes: tuple[str, ...]  # 捨てた観測など(記録用)


def _group_of(name: str, catalogue: Mapping[str, Deed]) -> str:
    return catalogue[name].group


def _monopolist(
    holdings: Mapping[str, Holding], catalogue: Mapping[str, Deed], group: str
) -> Player | None:
    """色グループを全部持つプレイヤー(いなければ None)。"""
    members = [d.name for d in street_groups(catalogue).get(group, ())]
    owners = {holdings[n].owner if n in holdings else None for n in members}
    if len(owners) == 1:
        (only,) = owners
        return only
    return None


def reconcile(
    state: MonopolyState,
    deeds: Mapping[str, DeedObservation | None],
    groups: Mapping[str, GroupObservation] | None,
    pending: Pending = frozenset(),
    catalogue: Mapping[str, Deed] = CATALOGUE,
    trusted: bool = False,
) -> Reconciliation:
    """台帳と観測を照合し、直した状態・保留・開いて確かめる色グループを返す。

    deeds: 土地の名前 → 観測。読めなかった土地は None(その土地は、台帳のままにする)。
    groups: 色グループ → 家とホテルの見積もり。読めなければ None(家の照合を飛ばす)。
    """
    holdings = dict(state.holdings)
    seen: set[tuple[str, str, str]] = set()
    fixes: list[str] = []
    unresolved: list[str] = []
    notes: list[str] = []
    open_groups: set[str] = set()

    for name, obs in deeds.items():
        if obs is None or name not in catalogue:
            continue
        held = holdings.get(name)
        if obs.owner is None:
            if held is not None:
                unresolved.append(f"{name}: 台帳は {held.owner.value} の所有だが、全体盤は無所有")
            continue
        if held is None or held.owner is not obs.owner:
            if held is not None and held.houses > 0:
                # 家のある土地は、売買できない。所有の読み違い、または台帳の家の誤り
                unresolved.append(
                    f"{name}: 台帳は {held.owner.value}(家 {held.houses})、全体盤は {obs.owner.value}"
                )
                open_groups.add(_group_of(name, catalogue))
                continue
            key = (name, "owner", obs.owner.value)
            if trusted or key in pending:
                holdings[name] = Holding(owner=obs.owner, mortgaged=obs.mortgaged is True)
                before = "無所有" if held is None else held.owner.value
                fixes.append(f"{name}: 所有 {before} → {obs.owner.value}")
            else:
                seen.add(key)
            continue
        if obs.mortgaged is not None and obs.mortgaged != held.mortgaged:
            key = (name, "mortgaged", str(obs.mortgaged))
            if trusted or key in pending:
                holdings[name] = replace(held, mortgaged=obs.mortgaged)
                fixes.append(f"{name}: 抵当 {held.mortgaged} → {obs.mortgaged}")
            else:
                seen.add(key)

    if groups is not None:
        for group, found in groups.items():
            owner = _monopolist(holdings, catalogue, group)
            members = [n for n, d in catalogue.items() if d.group == group]
            ledger_hotels = sum(
                1 for n in members if n in holdings and holdings[n].houses == HOTEL_LEVEL
            )
            ledger_units = sum(
                holdings[n].houses
                for n in members
                if n in holdings and holdings[n].houses < HOTEL_LEVEL
            )
            differs = (
                found.hotels != ledger_hotels
                or abs(found.house_units - ledger_units) >= HOUSE_UNITS_TOLERANCE
            )
            if not differs:
                continue
            if owner is None:
                # 独占でない色グループに家はありえない。全体盤の読み違いとして捨てる
                notes.append(
                    f"{group}: 全体盤は家 {found.house_units:.1f}・ホテル {found.hotels} だが、"
                    "台帳では独占されていない(誤読として捨てた)"
                )
                continue
            open_groups.add(group)
            notes.append(
                f"{group}: 家の見積もり {found.house_units:.1f}・ホテル {found.hotels} が、"
                f"台帳(家 {ledger_units}・ホテル {ledger_hotels})と違う。開いて確かめる"
            )

    return Reconciliation(
        state=MonopolyState(cash=state.cash, holdings=holdings),
        pending=frozenset(seen),
        fixes=tuple(fixes),
        open_groups=tuple(sorted(open_groups)),
        unresolved=tuple(unresolved),
        notes=tuple(notes),
    )


def with_houses(state: MonopolyState, houses: Mapping[str, int]) -> MonopolyState:
    """色グループを開いて読んだ、家の数(ホテルは 5)を、台帳へ反映する。所有されていない土地は無視する。"""
    holdings = dict(state.holdings)
    for name, count in houses.items():
        held = holdings.get(name)
        if held is not None and held.houses != count:
            holdings[name] = replace(held, houses=count)
    return MonopolyState(cash=state.cash, holdings=holdings)
