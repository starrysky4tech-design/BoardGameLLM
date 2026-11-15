"""札の表(data/birds.json)の読み込みと検査。

鳥は 180 枚のうち、対局で見えた札から増やしていく(RESULT.md §7、§8)。表に無い札は UnknownCardError とし、
置く・払うの対象にしない。**表の値は人が画像で確かめて入れる**(OCR の読み取りをそのまま入れない)。
"""

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from bglm.plugins.wingspan.logic.bonus import BonusCard
from bglm.plugins.wingspan.logic.models import (
    UNKNOWN_CARD,
    BirdCard,
    Food,
    FoodCost,
    Habitat,
    Nest,
    Power,
    Timing,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


# 画面から読めなかった鳥の代用札。点・卵の上限は 0 とし、得点を水増しせず、卵も置かない(置いた札として数えるだけ)
UNKNOWN_BIRD = BirdCard(
    name=UNKNOWN_CARD,
    habitats=frozenset(Habitat),
    cost=FoodCost(),
    points=0,
    nest=Nest.STAR,
    egg_limit=0,
    wingspan_cm=0,
    source="placeholder",
)


class UnknownCardError(KeyError):
    """札の表に無い札名。"""


@dataclass(frozen=True)
class CardTable:
    birds: dict[str, BirdCard]

    def bird(self, name: str) -> BirdCard:
        if name == UNKNOWN_CARD:
            return UNKNOWN_BIRD  # 読めなかった鳥は、中立の代用札として扱う(推測で値を入れない)
        try:
            return self.birds[name]
        except KeyError:
            raise UnknownCardError(name) from None

    def known(self, name: str) -> bool:
        return name in self.birds


def _power(raw: dict[str, Any]) -> Power:
    params = tuple(sorted((str(k), v) for k, v in raw.get("params", {}).items()))
    return Power(
        timing=Timing(raw.get("timing", "none")),
        kind=str(raw.get("kind", "")),
        params=params,
        text=str(raw.get("text", "")),
    )


def _bird(raw: dict[str, Any]) -> BirdCard:
    cost = raw["cost"]
    return BirdCard(
        name=raw["name"],
        habitats=frozenset(Habitat(h) for h in raw["habitats"]),
        cost=FoodCost(
            foods=tuple(Food(f) for f in cost["foods"]),
            wild=int(cost.get("wild", 0)),
            either=bool(cost.get("either", False)),
        ),
        points=int(raw["points"]),
        nest=Nest(raw["nest"]),
        egg_limit=int(raw["egg_limit"]),
        wingspan_cm=int(raw["wingspan_cm"]),
        power=_power(raw.get("power", {})),
        name_en=raw.get("name_en", ""),
        predator=bool(raw.get("predator", False)),
        flocking=bool(raw.get("flocking", False)),
        source=raw.get("source", ""),
    )


def load_birds(path: Path | None = None) -> CardTable:
    data = json.loads((path or DATA_DIR / "birds.json").read_text(encoding="utf-8"))
    birds = [_bird(b) for b in data["birds"]]
    names = [b.name for b in birds]
    duplicated = sorted({n for n in names if names.count(n) > 1})
    if duplicated:
        raise ValueError(f"札名が重複している: {duplicated}")
    return CardTable({b.name: b for b in birds})


@cache
def default_table() -> CardTable:
    return load_birds()


def load_bonus(path: Path | None = None) -> dict[str, BonusCard]:
    data = json.loads((path or DATA_DIR / "bonus.json").read_text(encoding="utf-8"))
    cards = [
        BonusCard(
            name=raw["name"],
            criterion=raw["criterion"],
            arg=raw.get("arg", ""),
            per_item=int(raw.get("per_item", 0)),
            tiers=tuple((int(lo), int(hi), int(pts)) for lo, hi, pts in raw.get("tiers", [])),
            source=raw.get("source", ""),
        )
        for raw in data["bonus"]
    ]
    return {c.name: c for c in cards}


@cache
def default_bonus() -> dict[str, BonusCard]:
    return load_bonus()
