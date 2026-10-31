"""Hive の手を、タップに変えて実行する(docs/02 の「MoveExecutor」)。

- 置く: 手持ちの駒の種類の位置をタップ → 置き先のマスをタップ
- 動かす: 動かす駒のマスをタップ → 移動先のマスをタップ
- 手番を放棄する(Pass): 操作の方法は未確認のため、実行しない(success=False で止まる)

座標: 盤の位置は画面ごとに変わるので、タップの直前に取得画像から求める。状態の座標は
読み取り(recognizer)と同じ向きに揃えてから、画面の座標へ変える。
実行の後は画面を読み直し、予測した盤面と一致したときだけ成功とする(画面が変わらなければ止まる)。
"""

import time
from collections.abc import Callable

import numpy as np
from numpy.typing import NDArray

from bglm.core.models import ExecutionResult, InputAction, Point, Tap
from bglm.core.protocols import GameIo
from bglm.plugins.hive.logic.models import (
    Color,
    HexCoord,
    HiveMove,
    HiveState,
    Kind,
    Move,
    Pass,
    Piece,
    Place,
)
from bglm.plugins.hive.logic.rules import HiveRules
from bglm.plugins.hive.vision.grid import HAND_BOTTOM, HAND_TOP, find_tiles, pixel_of, to_axial
from bglm.plugins.hive.vision.pieces import classify
from bglm.plugins.hive.vision.recognizer import HiveRecognizer, read_board

SETTLE_SEC = 1.5  # タップの後、アニメーションが収まるまでの待ち
VERIFY_TRIES = 3  # 画面を読み直す回数
VERIFY_WAIT_SEC = 1.0  # 読み直すまでの待ち


class HiveExecutor:
    def __init__(
        self,
        me: Color,
        rules: HiveRules | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._me = me
        self._rules = rules or HiveRules()
        self._recognizer = HiveRecognizer(me, self._rules)
        self._sleep = sleep

    def execute(self, io: GameIo, state: HiveState, move: HiveMove) -> ExecutionResult:
        match move:
            case Pass():
                return ExecutionResult(False, "pass_not_confirmed")
            case Place() | Move():
                return self._run(io, state, move)
        return ExecutionResult(False, f"未確認の操作: {type(move).__name__}")

    def _run(self, io: GameIo, state: HiveState, move: Place | Move) -> ExecutionResult:
        before = io.capture().image
        geometry = _geometry(before, state)
        if geometry is None:
            return ExecutionResult(False, "geometry_mismatch")
        offset, origin = geometry
        actions: list[InputAction] = []

        def tap(at: Point) -> None:
            action = Tap(at)
            io.perform(action)
            actions.append(action)
            self._sleep(SETTLE_SEC)

        def pixel(at: HexCoord) -> Point:
            x, y = pixel_of(HexCoord(at.q + offset.q, at.r + offset.r), (origin.x, origin.y))
            return Point(round(x), round(y))

        match move:
            case Place(kind=kind, to=to):
                hand = self._hand_tile(before, kind)
                if hand is None:
                    return ExecutionResult(False, f"hand_missing:{kind.value}")
                tap(hand)
                tap(pixel(to))
            case Move(frm=frm, to=to):
                tap(pixel(frm))
                tap(pixel(to))
        expected = self._rules.apply(state, move)
        if self._verified(io, expected):
            return ExecutionResult(True, actions=tuple(actions))
        return ExecutionResult(False, "verify_failed", tuple(actions))

    def _hand_tile(self, image: NDArray[np.uint8], kind: Kind) -> Point | None:
        """自分の手持ちの列から、指定の種類の駒の位置を探す。"""
        for tile in find_tiles(image, HAND_TOP, HAND_BOTTOM):
            if tile.side is not self._me:
                continue
            reading = classify(tile.glyph_hsv)
            if reading.kind is kind:
                return Point(round(tile.x), round(tile.y))
        return None

    def _verified(self, io: GameIo, expected: HiveState) -> bool:
        """自分の手の後の盤が読めるか。相手はこの間に応手することがあるので、
        自分の手の直後の盤、またはその後の相手の1手までを成功とする(盤が変わっていなければ失敗)。
        """
        for _ in range(VERIFY_TRIES):
            rec = self._recognizer.recognize(io.capture().image, expected)
            if rec.state is not None and expected.turn <= rec.state.turn <= expected.turn + 1:
                return True
            self._sleep(VERIFY_WAIT_SEC)
        return False


def _tops(state: HiveState) -> dict[HexCoord, Piece]:
    out: dict[HexCoord, Piece] = {}
    for at in state.occupied():
        top = state.top(at)
        if top is not None:
            out[at] = top
    return out


def _geometry(image: NDArray[np.uint8], state: HiveState) -> tuple[HexCoord, Point] | None:
    """状態の座標 → 画面の座標の平行移動(offset)と、軸座標 (0,0) のマスの中心(origin)。

    読み取った駒の配置と状態の駒の配置が、ずれだけで一致しなければ None。
    """
    reading = read_board(image)
    if reading.problems or not reading.tops:
        return None
    placed = to_axial(find_tiles(image))
    if placed is None or HexCoord(0, 0) not in placed:
        return None
    state_tops = _tops(state)
    if not state_tops:
        return None
    offset = HexCoord(
        min(at.q for at in reading.tops) - min(at.q for at in state_tops),
        min(at.r for at in reading.tops) - min(at.r for at in state_tops),
    )
    shifted = {HexCoord(at.q + offset.q, at.r + offset.r): p for at, p in state_tops.items()}
    if shifted != reading.tops:
        return None
    origin_tile = placed[HexCoord(0, 0)]
    return offset, Point(round(origin_tile.x), round(origin_tile.y))
