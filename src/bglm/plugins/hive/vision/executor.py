"""Hive の手を、タップに変えて実行する(docs/02 の「MoveExecutor」)。

- 置く: 手持ちの駒の種類の位置をタップ → 置き先のマスをタップ
- 動かす: 動かす駒のマスをタップ → 移動先のマスをタップ
- 手番を放棄する(Pass): 操作の方法は未確認のため、実行しない(success=False で止まる)

座標: 盤が画面より広いときは、3枚を継ぎ合わせた全体の座標から、タップの位置を求める(wide.py)。
打つマスが画面に写っていなければ、寄せてから読み直す。実行の後は全体を読み直し、
予測した盤面(自分の手、またはその後の相手の1手)と一致したときだけ成功とする。
"""

import time
from collections.abc import Callable

from bglm.core.models import ExecutionResult, Point, Tap
from bglm.core.protocols import GameIo
from bglm.plugins.hive.logic.models import (
    Color,
    HexCoord,
    HiveMove,
    HiveState,
    Kind,
    Move,
    Pass,
    Place,
)
from bglm.plugins.hive.logic.rules import HiveRules
from bglm.plugins.hive.vision.grid import HAND_BOTTOM, HAND_TOP, find_tiles, pixel_of, to_axial
from bglm.plugins.hive.vision.pieces import classify
from bglm.plugins.hive.vision.recognizer import HiveRecognizer, read_tiles, tops_of
from bglm.plugins.hive.vision.wide import SCREEN_W, WideView, pan_content, visible, wide_read
from bglm.toolkit.waiting import poll

SETTLE_SEC = 1.5  # タップの後、アニメーションが収まるまでの待ち
VERIFY_TRIES = 3  # 全体を読み直す回数
VERIFY_WAIT_SEC = 1.0  # 読み直すまでの待ち
VIEW_TRIES = 4  # 打つマスが見えるように寄せる回数の上限


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
        view: WideView | None = None
        board_taps: list[Point] = []
        for _ in range(VIEW_TRIES):
            view = wide_read(io, self._sleep)
            geometry = _geometry(view, state)
            if geometry is None:
                return ExecutionResult(False, "geometry_mismatch")
            board_taps = self._board_taps(move, geometry)
            hidden = [p for p in board_taps if not visible(p.x, p.y)]
            if not hidden:
                break
            # 見えない点を、画面の中央へ寄せる
            pan_content(io, round(SCREEN_W / 2 - hidden[0].x), self._sleep)
        else:
            return ExecutionResult(False, "not_visible")
        assert view is not None

        actions: list[Tap] = []

        def tap(at: Point) -> None:
            action = Tap(at)
            io.perform(action)
            actions.append(action)
            self._sleep(SETTLE_SEC)

        if isinstance(move, Place):
            hand = self._hand_tile(view.centre, move.kind)
            if hand is None:
                return ExecutionResult(False, f"hand_missing:{move.kind.value}")
            tap(hand)
        for at in board_taps:
            tap(at)
        expected = self._rules.apply(state, move)
        if self._verified(io, expected):
            return ExecutionResult(True, actions=tuple(actions))
        return ExecutionResult(False, "verify_failed", tuple(actions))

    def _board_taps(self, move: Place | Move, geometry: tuple[HexCoord, Point]) -> list[Point]:
        """盤の上のタップ(置き先、または移動元と移動先)。"""
        offset, origin = geometry
        targets = [move.to] if isinstance(move, Place) else [move.frm, move.to]

        def pixel(at: HexCoord) -> Point:
            x, y = pixel_of(HexCoord(at.q + offset.q, at.r + offset.r), (origin.x, origin.y))
            return Point(round(x), round(y))

        return [pixel(at) for at in targets]

    def _hand_tile(self, image: object, kind: Kind) -> Point | None:
        """自分の手持ちの列から、指定の種類の駒の位置を探す。"""
        for tile in find_tiles(image, HAND_TOP, HAND_BOTTOM):  # type: ignore[arg-type]
            if tile.side is not self._me:
                continue
            reading = classify(tile.glyph_hsv)
            if reading.kind is kind:
                return Point(round(tile.x), round(tile.y))
        return None

    def _verified(self, io: GameIo, expected: HiveState) -> bool:
        """全体を読み直し、予測と一致するか。相手の応手(1手)までは成功とする。"""
        _, ok = poll(
            lambda: self._recognizer.recognize_reading(
                read_tiles(wide_read(io, self._sleep).tiles), expected
            ),
            lambda rec: (
                rec.state is not None and expected.turn <= rec.state.turn <= expected.turn + 1
            ),
            tries=VERIFY_TRIES,
            wait_sec=VERIFY_WAIT_SEC,
            sleep=self._sleep,
            wait_last=True,
        )
        return ok


def _geometry(view: WideView, state: HiveState) -> tuple[HexCoord, Point] | None:
    """状態の座標 → 中央の画面の座標の平行移動(offset)と、軸座標 (0,0) のマスの中心(origin)。

    読み取った全体の駒の配置と、状態の駒の配置が、ずれだけで一致しなければ None。
    """
    reading = read_tiles(view.tiles)
    if reading.problems or not reading.tops:
        return None
    placed = to_axial(view.tiles)
    if placed is None or HexCoord(0, 0) not in placed:
        return None
    state_tops = tops_of(state)
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
