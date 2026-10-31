"""Hive のテスト用の盤面の組み立て。座標は軸座標 (q, r)。手持ちは既定で0(全部置き終えた状態)。"""

from collections.abc import Iterable, Mapping

from bglm.plugins.hive.logic.models import Color, HexCoord, HiveState, Kind, Piece

Spec = tuple[int, int, Color, Kind]


def at(q: int, r: int) -> HexCoord:
    return HexCoord(q, r)


def board(pieces: Iterable[Spec]) -> dict[HexCoord, tuple[Piece, ...]]:
    stacks: dict[HexCoord, tuple[Piece, ...]] = {}
    for q, r, color, kind in pieces:
        stacks[HexCoord(q, r)] = stacks.get(HexCoord(q, r), ()) + (Piece(color, kind),)
    return stacks


def state(
    pieces: Iterable[Spec] = (),
    hand: Mapping[tuple[Color, Kind], int] | None = None,
    to_move: Color = Color.WHITE,
    turn: int = 2,
) -> HiveState:
    """手持ちの既定は0。女王を置く前の局面は hand で指定する。"""
    return HiveState(stacks=board(pieces), hand=dict(hand or {}), to_move=to_move, turn=turn)


W, B = Color.WHITE, Color.BLACK


def tops_of(s: HiveState) -> dict[HexCoord, Piece]:
    """盤の一番上の駒。画面に見える駒と同じ。"""
    return {at: top for at in s.occupied() if (top := s.top(at)) is not None}
