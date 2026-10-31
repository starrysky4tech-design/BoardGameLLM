"""Kahuna のテスト用の組み立て補助。島と点線は名前で指定する。"""

from typing import Any

from bglm.plugins.kahuna.logic.models import (
    BoardDef,
    KahunaState,
    Player,
    default_board,
)

BOARD: BoardDef = default_board()
ME, OPP = Player.ME, Player.OPPONENT


def island(name: str) -> int:
    return BOARD.island_index(name)


def line(a: str, b: str) -> int:
    return BOARD.line_between(island(a), island(b))


def empty_sticks() -> list[Player | None]:
    return [None] * len(BOARD.lines)


def empty_stones() -> list[Player | None]:
    return [None] * len(BOARD.islands)


def make_state(
    sticks: dict[tuple[str, str], Player] | None = None,
    stones: dict[str, Player] | None = None,
    hand: tuple[str, ...] = (),
    market: tuple[str, ...] = (),
    **overrides: Any,
) -> KahunaState:
    """名前で指定した杖コマ・カフナコマ・手札・場札から、自分視点の盤面を作る。"""
    stick_list = empty_sticks()
    for (a, b), owner in (sticks or {}).items():
        stick_list[line(a, b)] = owner
    stone_list = empty_stones()
    for name, owner in (stones or {}).items():
        stone_list[island(name)] = owner
    base: dict[str, Any] = {
        "sticks": tuple(stick_list),
        "stones": tuple(stone_list),
        "hand": tuple(island(c) for c in hand),
        "market": tuple(island(c) for c in market),
        "deck_count": 10,
        "round": 1,
        "scores": (0, 0),
    }
    base.update(overrides)
    return KahunaState(**base)
