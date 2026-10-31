"""Hive の状態と手の表現。画面にも VLM にも依存しない(docs/02 の「Hiveのモデル」)。

盤は固定せず、駒のスタック(下から上)を座標ごとに持つ。手持ちは (色, 種類) ごとの残り数。
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum, IntEnum


class Color(IntEnum):
    WHITE = 0  # 先手
    BLACK = 1


class Kind(Enum):
    QUEEN = "queen"
    ANT = "ant"
    BEETLE = "beetle"
    GRASSHOPPER = "grasshopper"
    SPIDER = "spider"


# 1色あたりの手持ち。実機の表示から目視で数えた値(docs/02。Phase 2 でルールと照らして確定する)
HAND_PER_COLOR: Mapping[Kind, int] = {
    Kind.QUEEN: 1,
    Kind.ANT: 3,
    Kind.BEETLE: 2,
    Kind.GRASSHOPPER: 3,
    Kind.SPIDER: 2,
}

# 自分の手番の通し番号(0始まり)がこれ以下の間に女王を置く。アプリ内の「4手目まで」(Tutorial 4/12)
QUEEN_DEADLINE_INDEX = 3

# 軸座標の6方向
DIRECTIONS: tuple[tuple[int, int], ...] = ((1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1))


def opponent(color: Color) -> Color:
    return Color.BLACK if color is Color.WHITE else Color.WHITE


@dataclass(frozen=True, order=True)
class HexCoord:
    q: int
    r: int

    def __add__(self, other: "HexCoord") -> "HexCoord":
        return HexCoord(self.q + other.q, self.r + other.r)

    def neighbors(self) -> tuple["HexCoord", ...]:
        return tuple(self + HexCoord(dq, dr) for dq, dr in DIRECTIONS)


@dataclass(frozen=True)
class Piece:
    color: Color
    kind: Kind


@dataclass(frozen=True)
class Place:
    """手持ちの駒を置く。"""

    kind: Kind
    to: HexCoord


@dataclass(frozen=True)
class Move:
    """盤上の一番上の駒を動かす。"""

    frm: HexCoord
    to: HexCoord


@dataclass(frozen=True)
class Pass:
    """動ける手が無いときの手番の放棄。動ける手が無いときだけ使う(既定値。docs/02)。"""


HiveMove = Place | Move | Pass


@dataclass(frozen=True)
class HiveState:
    stacks: Mapping[HexCoord, tuple[Piece, ...]] = field(default_factory=dict)  # 下から上
    hand: Mapping[tuple[Color, Kind], int] = field(default_factory=dict)  # 手持ちの残り数
    to_move: Color = Color.WHITE
    turn: int = 0  # 手番の通し番号。パスも1手番に数える

    def top(self, at: HexCoord) -> Piece | None:
        stack = self.stacks.get(at)
        return stack[-1] if stack else None

    def occupied(self) -> frozenset[HexCoord]:
        return frozenset(self.stacks)

    def remaining(self, color: Color, kind: Kind) -> int:
        return self.hand.get((color, kind), 0)

    def own_turn_index(self) -> int:
        """手番を持つ側の、自分の何手目か(0始まり)。"""
        return self.turn // 2

    def queen_at(self, color: Color) -> HexCoord | None:
        for at, stack in self.stacks.items():
            if any(p.color is color and p.kind is Kind.QUEEN for p in stack):
                return at
        return None

    def normalized(self) -> "HiveState":
        """盤の絶対位置に依らない形にする。最小の q と r が 0 になるように平行移動する。"""
        if not self.stacks:
            return self
        min_q = min(at.q for at in self.stacks)
        min_r = min(at.r for at in self.stacks)
        shift = HexCoord(-min_q, -min_r)
        moved = {at + shift: stack for at, stack in self.stacks.items()}
        return HiveState(stacks=moved, hand=dict(self.hand), to_move=self.to_move, turn=self.turn)


def initial_state() -> HiveState:
    hand = {(color, kind): n for color in Color for kind, n in HAND_PER_COLOR.items()}
    return HiveState(stacks={}, hand=hand, to_move=Color.WHITE, turn=0)
