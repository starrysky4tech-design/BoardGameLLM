"""Maquis の盤(地点と道)。画面にも VLM にも依存しない(docs/04 の logic の規則)。

地点は文字列の id で表す(data/board.json)。団員は隠れ家へ道をたどって戻る。巡回のいる地点は通れない。
"""

import json
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

BOARD_PATH = Path(__file__).resolve().parents[1] / "data" / "board.json"

# 道が無く、団員が戻る先でも通り道でもない地点(捕縛された団員の置き場)
PRISON_KIND = "prison"
HIDEOUT_KIND = "hideout"


@dataclass(frozen=True)
class Board:
    kinds: Mapping[str, str]  # 地点 id → 種類(town / radio / spare_room / field / hideout / prison)
    names: Mapping[str, str]  # 地点 id → 画面の表示名(同名の地点がある: 空き部屋、畑)
    neighbors: Mapping[str, frozenset[str]]
    hideout: str
    missions: Mapping[str, str] = field(default_factory=dict)  # 任務の枠 id → 帰還を判定する地点 id

    def node_of(self, slot: str) -> str:
        """団員のいる枠(地点、または任務の枠)の、帰還を判定する地点。"""
        return self.missions.get(slot, slot)

    def locations(self) -> tuple[str, ...]:
        """団員を送れる地点(隠れ家と監獄を除く)。"""
        return tuple(i for i, k in self.kinds.items() if k not in (HIDEOUT_KIND, PRISON_KIND))

    def reachable_from_hideout(self, blocked: Iterable[str] = ()) -> frozenset[str]:
        """巡回のいる地点 `blocked` を通らずに、隠れ家から道でたどり着ける地点(隠れ家を含む)。"""
        stop = frozenset(blocked) - {self.hideout}
        seen = {self.hideout}
        queue = deque([self.hideout])
        while queue:
            here = queue.popleft()
            for there in self.neighbors[here]:
                if there not in seen and there not in stop:
                    seen.add(there)
                    queue.append(there)
        return frozenset(seen)

    def marked(self, blocked: Iterable[str] = ()) -> frozenset[str]:
        """画面で赤い「!」が付く地点(巡回のいる地点を含む)。

        巡回のいる地点を通らずに隠れ家からたどり着ける地点(`reachable_from_hideout`)の、さらに隣までは
        「戻れる」。巡回のいる地点は、そこに隣り合う到達可能な地点があれば「!」が付かない。
        実機の観測3件の全リストと一致した(2026-11-11)。
        """
        stop = frozenset(blocked)
        ok = self.reachable_from_hideout(stop)
        endpoint = set(ok) | {n for n in stop if self.neighbors[n] & ok}
        return frozenset(i for i in self.locations() if i not in endpoint)

    def stranded(self, blocked: Iterable[str] = ()) -> frozenset[str]:
        """画面に赤い「!」が付く地点。巡回のいない地点のうち、隠れ家へ戻れない(団員がいれば捕縛される)もの。"""
        stop = frozenset(blocked)
        ok = self.reachable_from_hideout(stop)
        return frozenset(i for i in self.locations() if i not in stop and i not in ok)


def load_board(path: Path = BOARD_PATH) -> Board:
    data = json.loads(path.read_text(encoding="utf-8"))
    kinds = {n["id"]: n["kind"] for n in data["nodes"]}
    names = {n["id"]: n["name"] for n in data["nodes"]}
    adjacent: dict[str, set[str]] = {i: set() for i in kinds}
    for a, b in data["edges"]:
        if a not in kinds or b not in kinds:
            raise ValueError(f"道の端が地点に無い: {a}, {b}")
        adjacent[a].add(b)
        adjacent[b].add(a)
    hideout = data["hideout"]
    if kinds.get(hideout) != HIDEOUT_KIND:
        raise ValueError(f"隠れ家の指定が不正: {hideout}")
    missions = dict(data.get("missions", {}))
    for slot, node in missions.items():
        if node not in kinds:
            raise ValueError(f"任務の枠 {slot} の地点が無い: {node}")
    return Board(
        kinds=kinds,
        names=names,
        neighbors={i: frozenset(v) for i, v in adjacent.items()},
        hideout=hideout,
        missions=missions,
    )


def default_board() -> Board:
    return load_board()
