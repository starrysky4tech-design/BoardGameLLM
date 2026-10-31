"""Hive のルールの単体テスト。期待値は docs/ideas/Hive_アプリ内ルール.md(アプリ内の説明)から手で作る。

出典の表記: (Tutorial n/12) はアプリ内の Main tutorial、(Edge cases n/2) は Rules > Edge cases。
"""

from tests.plugins.hive.support.helpers import B, W, at, state

from bglm.plugins.hive.logic.models import (
    Color,
    HiveState,
    Kind,
    Move,
    Pass,
    Place,
    initial_state,
)
from bglm.plugins.hive.logic.rules import HiveRules, can_slide, hive_connected

RULES = HiveRules()


def moves_of(s: HiveState) -> list[object]:
    return list(RULES.legal_moves(s))


def test_first_placement_is_at_origin_for_white() -> None:
    # Tutorial 2/12: 盤が空の状態で白が最初に駒を置く
    moves = RULES.legal_moves(initial_state())
    assert all(isinstance(m, Place) and m.to == at(0, 0) for m in moves)
    assert {m.kind for m in moves if isinstance(m, Place)} == set(Kind)


def test_black_first_placement_touches_white_piece() -> None:
    # Tutorial 2/12: 黒は白の駒の隣に置く(この1手だけは相手の隣に置ける)
    s = state([(0, 0, W, Kind.ANT)], hand={(B, Kind.ANT): 1}, to_move=B, turn=1)
    spots = {m.to for m in RULES.legal_moves(s) if isinstance(m, Place)}
    assert spots == set(at(0, 0).neighbors())


def test_placement_may_not_touch_opponent() -> None:
    # Tutorial 3/12: 新しい駒は相手の駒の隣に置けない
    # 白のアリ(0,0)と黒のカブトムシ(1,0)。(1,-1)と(0,1)は黒の隣なので不可
    s = state(
        [(0, 0, W, Kind.ANT), (1, 0, B, Kind.BEETLE)],
        hand={(W, Kind.SPIDER): 1},
        turn=2,
    )
    spots = {m.to for m in RULES.legal_moves(s) if isinstance(m, Place)}
    assert spots == {at(0, -1), at(-1, 0), at(-1, 1)}


def test_queen_must_be_placed_by_fourth_turn() -> None:
    # Tutorial 4/12: 4手目までに女王を置く。その手番では女王しか置けない
    hand = {(W, Kind.QUEEN): 1, (W, Kind.SPIDER): 1}
    s = state([(0, 0, W, Kind.ANT), (1, 0, B, Kind.BEETLE)], hand=hand, turn=6)
    moves = moves_of(s)
    assert moves and all(isinstance(m, Place) and m.kind is Kind.QUEEN for m in moves)


def test_no_piece_moves_before_queen_is_placed() -> None:
    # Tutorial 4/12: 女王を置くまで駒を動かせない
    hand = {(W, Kind.QUEEN): 1}
    s = state([(0, 0, W, Kind.ANT), (1, 0, B, Kind.BEETLE)], hand=hand, turn=2)
    assert not any(isinstance(m, Move) for m in moves_of(s))


def test_one_hive_rule_forbids_splitting() -> None:
    # Tutorial 5/12: ハイブを2つに割る移動は禁止。(1,0)の駒は動かすと(2,0)が切り離される
    s = state(
        [(0, 0, W, Kind.QUEEN), (1, 0, W, Kind.ANT), (2, 0, B, Kind.SPIDER)],
        turn=4,
    )
    moves = moves_of(s)
    assert not any(isinstance(m, Move) and m.frm == at(1, 0) for m in moves)
    # 女王は(0,1)へ動いても、(1,0)とつながるので合法
    assert Move(at(0, 0), at(0, 1)) in moves


def test_gate_blocks_sliding() -> None:
    # Tutorial 11/12: 共通の隣が両方埋まっていると滑り込めない
    base = frozenset({at(1, -1), at(0, 1)})  # (0,0)と(1,0)の共通の隣
    assert not can_slide(base, at(0, 0), at(1, 0))
    assert can_slide(frozenset({at(1, -1)}), at(0, 0), at(1, 0))


def test_grasshopper_jumps_over_pieces_to_first_empty() -> None:
    # Tutorial 8/12: 直線上の駒を1つ以上越えて、次の空きマスへ跳ぶ
    s = state(
        [(0, 0, W, Kind.GRASSHOPPER), (1, 0, W, Kind.QUEEN), (2, 0, B, Kind.ANT)],
        turn=4,
    )
    moves = moves_of(s)
    assert Move(at(0, 0), at(3, 0)) in moves
    assert Move(at(0, 0), at(1, 0)) not in moves


def test_beetle_can_climb_onto_occupied_cell() -> None:
    # Tutorial 7/12: カブトムシは隣へ動ける。駒の上にも乗れる
    s = state(
        [(0, 0, W, Kind.QUEEN), (1, 0, W, Kind.BEETLE), (-1, 0, B, Kind.ANT)],
        turn=4,
    )
    assert Move(at(1, 0), at(0, 0)) in moves_of(s)


def test_queen_is_surrounded_loses_for_the_side_to_move() -> None:
    # Tutorial 1/12: 相手の女王を6方向すべて囲んだ側が勝つ。囲まれたのは手番の側(相手の手で囲まれた)
    ring = [(n.q, n.r, B, Kind.ANT) for n in at(0, 0).neighbors()]
    s = state([(0, 0, W, Kind.QUEEN), *ring], turn=12, to_move=W)
    assert RULES.is_terminal(s)
    assert RULES.outcome(s) == "lose"
    assert RULES.legal_moves(s) == []


def test_pass_when_no_move_is_possible() -> None:
    # 動ける手が無いときだけ Pass(既定値。docs/02)。手持ちも盤も空なら Pass
    s = state(hand={(W, Kind.QUEEN): 0}, turn=0)
    assert RULES.legal_moves(s) == [Pass()]


def test_apply_place_updates_hand_and_turn() -> None:
    s = RULES.apply(initial_state(), Place(Kind.QUEEN, at(0, 0)))
    assert s.remaining(Color.WHITE, Kind.QUEEN) == 0
    assert s.to_move is Color.BLACK
    assert s.turn == 1


def test_hive_connected_detects_a_split() -> None:
    assert hive_connected(frozenset({at(0, 0), at(1, 0)}))
    assert not hive_connected(frozenset({at(0, 0), at(2, 0)}))
    assert hive_connected(frozenset())
