"""ラウンドの目的タイルの数え方と採点(出典: ルールブック R p.11、付録 A p.3)。

目的タイルは 16 種(両面)。ここでは「何を数えるか」(count)と「順位から点への変換」(majority_points)を持つ。
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from bglm.plugins.wingspan.logic.models import (
    HABITATS,
    Habitat,
    Nest,
    PlayerBoard,
)

NestOf = Callable[[str], Nest]  # 札名 → 巣(cards.py の表から作る)


class GoalMode(StrEnum):
    MAJORITY = "majority"  # 緑の面: 順位で点(既定)
    PER_ITEM = "per_item"  # 青の面: 1 個につき 1 点、最大 5 点


# 緑の面の順位ごとの点(ラウンド 1〜4。R p.1 の目的ボード)。添字は順位(0 = 1 位)
MAJORITY_POINTS: tuple[tuple[int, int, int], ...] = ((4, 1, 0), (5, 2, 1), (6, 3, 2), (7, 4, 3))
PER_ITEM_MAX = 5


@dataclass(frozen=True)
class GoalTile:
    """数える対象。kind は下の `count_goal` で解釈する。"""

    kind: str  # birds_in_habitat / nest_birds_with_eggs / eggs_in_habitat / eggs_in_nest / egg_sets / total_birds
    arg: str = ""  # 生息地名または巣の名前。kind が "unknown" のときは、画面から読めなかった目的(0 点として扱う)


def all_goal_tiles() -> tuple[GoalTile, ...]:
    """16 種(A p.3)。生息地 × 2 種で 6、巣 × 2 種で 8、卵の組と鳥の総数で 2。"""
    tiles: list[GoalTile] = []
    for habitat in HABITATS:
        tiles.append(GoalTile("birds_in_habitat", habitat.value))
    for nest in (Nest.PLATFORM, Nest.BOWL, Nest.CAVITY, Nest.GROUND):
        tiles.append(GoalTile("nest_birds_with_eggs", nest.value))
    for habitat in HABITATS:
        tiles.append(GoalTile("eggs_in_habitat", habitat.value))
    for nest in (Nest.PLATFORM, Nest.BOWL, Nest.CAVITY, Nest.GROUND):
        tiles.append(GoalTile("eggs_in_nest", nest.value))
    tiles.append(GoalTile("egg_sets"))
    tiles.append(GoalTile("total_birds"))
    return tuple(tiles)


def _nest_matches(bird_nest: Nest, wanted: Nest) -> bool:
    """星の巣はどの巣の種類にも数える(A p.3)。"""
    return bird_nest == wanted or bird_nest == Nest.STAR


def count_goal(tile: GoalTile, board: PlayerBoard, nest_of: NestOf) -> int:
    match tile.kind:
        case "birds_in_habitat":
            return len(board.row(Habitat(tile.arg)))
        case "nest_birds_with_eggs":
            wanted = Nest(tile.arg)
            return sum(
                1 for b in board.birds() if b.eggs >= 1 and _nest_matches(nest_of(b.name), wanted)
            )
        case "eggs_in_habitat":
            return sum(b.eggs for b in board.row(Habitat(tile.arg)))
        case "eggs_in_nest":
            wanted = Nest(tile.arg)
            return sum(b.eggs for b in board.birds() if _nest_matches(nest_of(b.name), wanted))
        case "egg_sets":
            # 森林・草原・湿地に 1 個ずつで 1 組。どの鳥・どの列に載っているかは問わない(A p.3)
            per_row = [sum(b.eggs for b in board.rows[i]) for i in range(3)]
            return min(per_row)
        case "total_birds":
            return len(board.birds())
        case "unknown":
            return 0  # 画面から読めなかった目的。点にしない(推測しない)
    raise ValueError(f"未知の目的タイル: {tile}")


def majority_points(counts: list[int], round_index: int) -> list[int]:
    """緑の面の採点。counts は各プレイヤーの数(プレイヤーの順)、round_index は 0〜3。

    同順位は、その順位と次の順位の点を足して人数で割り、切り捨てる。次の順位は与えない(R p.11)。
    対象を 1 つも持たない(0)プレイヤーは 0 点(R p.11)。4 位以下は 0 点。
    """
    table = list(MAJORITY_POINTS[round_index]) + [0] * len(counts)
    order = sorted(range(len(counts)), key=lambda i: -counts[i])
    points = [0] * len(counts)
    pos = 0
    while pos < len(order):
        tied = [i for i in order[pos:] if counts[i] == counts[order[pos]]]
        share = sum(table[pos : pos + len(tied)]) // len(tied)
        for i in tied:
            points[i] = share if counts[i] >= 1 else 0
        pos += len(tied)
    return points


def per_item_points(counts: list[int]) -> list[int]:
    """青の面の採点。1 個につき 1 点、最大 5 点(R p.11)。"""
    return [min(c, PER_ITEM_MAX) for c in counts]


def goal_points(
    tile: GoalTile,
    boards: tuple[PlayerBoard, ...],
    round_index: int,
    mode: GoalMode,
    nest_of: NestOf,
) -> list[int]:
    counts = [count_goal(tile, b, nest_of) for b in boards]
    if mode is GoalMode.PER_ITEM:
        return per_item_points(counts)
    return majority_points(counts, round_index)
