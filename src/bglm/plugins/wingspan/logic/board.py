"""プレイヤーマットの数値(行動の強さ、卵のコスト)。出典はルールブック(R)と、実機の全体ボードの表示。

ルールブック p.4〜9 と、アプリの全体ボード(RESULT.md §2)の 6 つの枠で一致を確かめた。
行動の枠は「その行の鳥の数」で決まる(鳥が n 羽なら、左から n+1 番目の枠にキューブを置く。R p.4)。
"""

from bglm.plugins.wingspan.logic.models import Action, Habitat

MAX_BIRDS_PER_ROW = 5  # R p.6: 1 つの生息地に置ける鳥は 5 羽まで

# 鳥をプレイするときの卵のコスト。添字は「置く枠」(その行の鳥の数)。1 列目は 0、2〜3 列目は 1、4〜5 列目は 2(R p.6)
EGG_COST_BY_SLOT: tuple[int, ...] = (0, 1, 1, 2, 2)

# 行動の強さ。添字は「その行の鳥の数」(0〜5)。値は (個数, 変換あり)
# 変換 = 森林は「手札の鳥 1 枚を捨てて餌 +1」、草原は「餌 1 個を払って卵 +1」、湿地は「卵 1 個を捨てて札 +1」(R p.7〜9)
_STRENGTH: dict[Habitat, tuple[tuple[int, bool], ...]] = {
    Habitat.FOREST: ((1, False), (1, True), (2, False), (2, True), (3, False), (3, True)),
    Habitat.GRASSLAND: ((2, False), (2, True), (3, False), (3, True), (4, False), (4, True)),
    Habitat.WETLAND: ((1, False), (1, True), (2, False), (2, True), (3, False), (3, True)),
}

HABITAT_ACTION: dict[Habitat, Action] = {
    Habitat.FOREST: Action.GAIN_FOOD,
    Habitat.GRASSLAND: Action.LAY_EGGS,
    Habitat.WETLAND: Action.DRAW_CARDS,
}


def action_strength(habitat: Habitat, birds_in_row: int) -> tuple[int, bool]:
    """その行の行動の (個数, 変換あり)。鳥が 5 羽以上でも最後の枠(5 羽の枠)を使う。"""
    slots = _STRENGTH[habitat]
    return slots[min(birds_in_row, len(slots) - 1)]


def egg_cost(birds_in_row: int) -> int | None:
    """鳥をプレイするときに払う卵の数。行が満杯なら None(置けない)。"""
    if birds_in_row >= MAX_BIRDS_PER_ROW:
        return None
    return EGG_COST_BY_SLOT[birds_in_row]


# 1 ラウンドの手番数(R p.5)。キューブは 1 手番につき 1 個使う
TURNS_PER_ROUND: tuple[int, ...] = (8, 7, 6, 5)
ROUNDS = len(TURNS_PER_ROUND)

# 初期の手札(R p.2)
INITIAL_BIRD_CARDS = 5
INITIAL_BONUS_CARDS = 2
TRAY_SIZE = 3
FEEDER_DICE = 5
