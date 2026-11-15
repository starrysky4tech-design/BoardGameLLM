"""Wingspan の状態とデータモデル(docs の正本は .steering/20261112-phase-wingspan/02_DESIGN.md)。

画面に依存しない。状態は不変(frozen)にして、`Rules.apply` が新しい状態を返す。
札は名前(アプリの日本語の札名)で持ち、静的な値は `cards.py` の表で引く。
実機の追跡では、読めなかった札を UNKNOWN_CARD として持つ(推測で埋めない)。
"""

from dataclasses import dataclass, field, replace
from enum import StrEnum

UNKNOWN_CARD = "?"  # 読めなかった札・見えない札。置く・払うの対象にしない


class Food(StrEnum):
    INVERTEBRATE = "invertebrate"  # 虫
    SEED = "seed"  # 種
    FISH = "fish"  # 魚
    FRUIT = "fruit"  # 果実
    RODENT = "rodent"  # ネズミ


FOODS: tuple[Food, ...] = tuple(Food)  # 餌の並びの正本(PlayerBoard.food の添字)

# ダイスの目。5 種の餌のほかに、虫 / 種のどちらか 1 つを選ぶ面がある(R p.7)
INV_OR_SEED = "invertebrate_or_seed"
FEEDER_DICE_FACES: tuple[str, ...] = (*(f.value for f in FOODS), INV_OR_SEED)  # ダイスの 6 つの面


class Habitat(StrEnum):
    FOREST = "forest"  # 森林
    GRASSLAND = "grassland"  # 草原
    WETLAND = "wetland"  # 湿地


HABITATS: tuple[Habitat, ...] = tuple(Habitat)  # 行の並びの正本(PlayerBoard.rows の添字)


class Nest(StrEnum):
    PLATFORM = "platform"  # 皿
    BOWL = "bowl"  # 椀
    CAVITY = "cavity"  # 樹洞
    GROUND = "ground"  # 地上
    STAR = "star"  # 星(どの種類にも数える。R p.8)


class Timing(StrEnum):
    NONE = "none"
    WHEN_PLAYED = "when_played"  # 白
    WHEN_ACTIVATED = "when_activated"  # 茶
    BETWEEN_TURNS = "between_turns"  # 桃


class Action(StrEnum):
    PLAY_BIRD = "play_bird"
    GAIN_FOOD = "gain_food"
    LAY_EGGS = "lay_eggs"
    DRAW_CARDS = "draw_cards"


@dataclass(frozen=True)
class FoodCost:
    """鳥の餌のコスト。

    - `foods`: 必ず払う餌(「+」)。`either=True` のときは、どれか 1 つを払う(「/」)
    - `wild`: 何の餌でもよい個数(R p.6)
    """

    foods: tuple[Food, ...] = ()
    wild: int = 0
    either: bool = False

    def total(self) -> int:
        """払う餌の総数。「/」は 1 つだけ払う。"""
        return 1 if self.either else len(self.foods) + self.wild


@dataclass(frozen=True)
class Power:
    """鳥の能力。種類(kind)とパラメータで表す。実装の無い kind は Unmodeled として扱う(powers/registry.py)。"""

    timing: Timing = Timing.NONE
    kind: str = ""
    params: tuple[tuple[str, str | int], ...] = ()
    text: str = ""  # 札の文(出典)

    def param(self, name: str, default: str | int = 0) -> str | int:
        for key, value in self.params:
            if key == name:
                return value
        return default


@dataclass(frozen=True)
class BirdCard:
    name: str
    habitats: frozenset[Habitat]
    cost: FoodCost
    points: int
    nest: Nest
    egg_limit: int
    wingspan_cm: int
    power: Power = field(default_factory=Power)
    name_en: str = ""  # 名前のボーナスの判定用(付録 p.4)。未記入なら判定しない
    predator: bool = False
    flocking: bool = False  # 差し込み(群れ)の能力を持つ
    source: str = ""  # 出典(画像名)


@dataclass(frozen=True)
class PlacedBird:
    name: str
    eggs: int = 0
    cached: int = 0  # 蓄えた餌(1 点ずつ)
    tucked: int = 0  # 差し込んだ札(1 点ずつ)
    used: bool = False  # 桃色の能力を、手番と手番の間に使い済み(自分の次の手番で戻る。R p.10)


@dataclass(frozen=True)
class PlayerBoard:
    rows: tuple[tuple[PlacedBird, ...], tuple[PlacedBird, ...], tuple[PlacedBird, ...]] = (
        (),
        (),
        (),
    )
    food: tuple[int, int, int, int, int] = (0, 0, 0, 0, 0)  # FOODS の並び
    hand: tuple[str, ...] = ()
    bonus: tuple[str, ...] = ()
    cubes: int = 8
    goal_points: tuple[int, ...] = ()  # 終えたラウンドの目的の点

    def row(self, habitat: Habitat) -> tuple[PlacedBird, ...]:
        return self.rows[HABITATS.index(habitat)]

    def count(self, food: Food) -> int:
        return self.food[FOODS.index(food)]

    def birds(self) -> tuple[PlacedBird, ...]:
        return self.rows[0] + self.rows[1] + self.rows[2]

    def bird_at(self, at: "Placement") -> PlacedBird:
        return self.row(at.habitat)[at.index]

    def with_bird(self, at: "Placement", bird: PlacedBird) -> "PlayerBoard":
        """at の鳥を bird に替えた盤。"""
        i = HABITATS.index(at.habitat)
        row = self.rows[i][: at.index] + (bird,) + self.rows[i][at.index + 1 :]
        return self.with_row(at.habitat, row)

    def with_row(self, habitat: Habitat, row: tuple[PlacedBird, ...]) -> "PlayerBoard":
        i = HABITATS.index(habitat)
        rows = list(self.rows)
        rows[i] = row
        return replace(self, rows=(rows[0], rows[1], rows[2]))

    def with_food(self, food: Food, delta: int) -> "PlayerBoard":
        i = FOODS.index(food)
        counts = list(self.food)
        counts[i] += delta
        return replace(self, food=(counts[0], counts[1], counts[2], counts[3], counts[4]))

    def placements(self) -> tuple["Placement", ...]:
        return tuple(Placement(h, i) for h in HABITATS for i in range(len(self.row(h))))


@dataclass(frozen=True)
class Placement:
    """盤の上の 1 羽の位置。"""

    habitat: Habitat
    index: int  # 行の左から 0 始まり
