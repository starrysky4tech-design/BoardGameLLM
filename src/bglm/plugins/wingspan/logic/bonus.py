"""ボーナスカードの数え方と点(出典: 付録 A p.4〜5)。

数え方(criterion)は付録の分類に合わせる。点は札ごとに違う(1 枚につき n 点、または数の段階ごとの点)ので、
札の表(data/bonus.json)が持つ。ここでは数え方と、数から点への変換だけを実装する。
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

from bglm.plugins.wingspan.logic.models import (
    BirdCard,
    Habitat,
    Nest,
    PlayerBoard,
)

BirdOf = Callable[[str], BirdCard]

# 名前のボーナスの語(A p.4)。英語の札名で判定する。部位は活用形(bellied など)も数える
_COLORS = (
    "ash black blue bronze brown cerulean chestnut ferruginous gold gray green indigo lazuli "
    "purple red rose roseate ruby ruddy snowy violet white yellow"
).split()
_ANATOMY = (
    "back beak belly bill breast cap chin collar crest crown eye face head neck rump shoulder "
    "tail throat wing"
).split()
_GEOGRAPHY = (
    "American Atlantic Baltimore California Canada Carolina Chihuahuan Eastern Inca Meadow "
    "Mississippi Mountain Northern Prairie Sandhill Savannah Western"
).split()

NAME_WORDS: dict[str, tuple[str, ...]] = {
    "color": tuple(_COLORS),
    "anatomy": tuple(_ANATOMY),
    "geography": tuple(_GEOGRAPHY),
}


@dataclass(frozen=True)
class BonusCard:
    name: str
    criterion: str
    arg: str = ""
    per_item: int = 0  # 1 つにつき n 点
    tiers: tuple[tuple[int, int, int], ...] = ()  # (下限, 上限, 点)。per_item が 0 のとき使う
    source: str = ""


def _tokens(name_en: str) -> list[str]:
    """英語名を単語に分ける。ハイフンでつながる語(Red-bellied)も別の語として扱う。"""
    return [t for t in re.split(r"[\s\-]+", name_en.lower()) if t]


def _forms(word: str) -> set[str]:
    """部位の語の活用形(A p.4: bellied のような形も数える)。belly → bellied、cap → capped など。"""
    forms = {word, word + "s", word + "ed", word + word[-1] + "ed"}
    if word.endswith("y"):
        forms |= {word[:-1] + "ied", word[:-1] + "ies"}
    return forms


def _has_name_word(card: BirdCard, group: str) -> bool:
    """名前のボーナスの判定。英語名が無い札は数えない(推測しない)。

    単語単位で照合する(部分一致だと Cape May の cap などを誤って数えるため)。
    色と地名は、単語がその語で始まるものを数える(Bluebird、Goldfinch、Meadowlark を含む想定)。
    **この想定は付録の文言からの推測で、実機のボーナスカードの数と照合して確かめる(未確認)**。
    """
    if not card.name_en:
        return False
    if group == "person":
        return "’s" in card.name_en or "'s" in card.name_en
    tokens = _tokens(card.name_en)
    words = [w.lower() for w in NAME_WORDS[group]]
    if group == "anatomy":
        return any(t in _forms(w) for t in tokens for w in words)
    return any(t.startswith(w) for t in tokens for w in words)


def count_bonus(bonus: BonusCard, board: PlayerBoard, bird_of: BirdOf) -> int:
    cards = [bird_of(b.name) for b in board.birds()]
    arg = bonus.arg
    match bonus.criterion:
        case "name":
            return sum(1 for c in cards if _has_name_word(c, arg))
        case "nest":
            wanted = Nest(arg)
            return sum(1 for c in cards if c.nest in (wanted, Nest.STAR))
        case "eggs_at_least":
            return sum(1 for b in board.birds() if b.eggs >= int(arg))
        case "habitat_only":
            only = Habitat(arg)
            return sum(1 for c in cards if c.habitats == frozenset({only}))
        case "fewest_habitat":
            return min(len(row) for row in board.rows)
        case "icon":
            if arg == "flocking":
                return sum(1 for c in cards if c.flocking)
            if arg == "predator":
                return sum(1 for c in cards if c.predator)
            raise ValueError(f"未知のアイコン: {arg}")
        case "wingspan_over":
            return sum(1 for c in cards if c.wingspan_cm > int(arg))
        case "wingspan_at_most":
            return sum(1 for c in cards if c.wingspan_cm <= int(arg))
        case "points_below":
            return sum(1 for c in cards if c.points < int(arg))
        case "hand_size":
            return len(board.hand)
        case "food_symbol":
            if arg == "wild":
                return sum(1 for c in cards if c.cost.wild > 0)
            return sum(1 for c in cards if arg in {f.value for f in c.cost.foods})
        case "food_only":
            return sum(
                1
                for c in cards
                if c.cost.foods and c.cost.wild == 0 and all(f.value == arg for f in c.cost.foods)
            )
    raise ValueError(f"未知のボーナスの数え方: {bonus.criterion}")


def bonus_points(bonus: BonusCard, count: int) -> int:
    if bonus.per_item:
        return bonus.per_item * count
    for low, high, pts in bonus.tiers:
        if low <= count <= high:
            return pts
    return 0


def score_bonus(bonus: BonusCard, board: PlayerBoard, bird_of: BirdOf) -> int:
    return bonus_points(bonus, count_bonus(bonus, board, bird_of))
