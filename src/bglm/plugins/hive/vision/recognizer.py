"""Hive の認識。1枚の取得画像から盤面を読み、直前の状態と照らして採用する(docs/02「Recognizer」)。

読み方:
1. マスを見つけ、軸座標に置く(grid.py)。絵の色から駒の種類を決める(pieces.py)
2. 地の色で側を決める。上に乗った駒は見えるが、下の駒は隠れる。隠れたマスの地が見えたら止める
3. 直前の状態に、合法手を1手打った結果と一致するなら採用する。一致しなければ止める

手持ちの数は画像からは読まず、直前の状態から追う(1手打つごとに1つ減る)。
"""

from dataclasses import dataclass

import cv2
import numpy as np
from numpy.typing import NDArray

from bglm.core.models import Frame, Recognition, UiKind, UiState
from bglm.core.protocols import GameIo
from bglm.plugins.hive.logic.models import Color, HexCoord, HiveState, Piece
from bglm.plugins.hive.logic.rules import HiveRules
from bglm.plugins.hive.vision.grid import (
    TILE_H,
    TILE_R,
    Tile,
    find_tiles,
    ground_masks,
    tile_hex_mask,
    to_axial,
)
from bglm.plugins.hive.vision.pieces import classify
from bglm.plugins.hive.vision.screens import ScreenKind, screen_of

ELEMENT_MIN = 0.5  # 要素の確信度がこれ未満なら採用しない
HIDDEN_GROUND_MAX = 2000  # マスで覆われていない地の画素の上限(隠れた駒の地が見えたとみなす)


class HiveRecognizer:
    def __init__(self, me: Color, rules: HiveRules | None = None) -> None:
        self._me = me
        self._rules = rules or HiveRules()

    def observe(self, io: GameIo, previous: HiveState | None) -> Recognition[HiveState]:
        frame: Frame = io.capture()
        return self.recognize(frame.image, previous)

    def recognize(
        self, image: NDArray[np.uint8], previous: HiveState | None
    ) -> Recognition[HiveState]:
        reading = read_board(image)
        screen = screen_of(bool(reading.tops), reading.problems)
        if screen is not ScreenKind.BOARD:
            return _unknown(reading.confidence, (screen.value, *reading.problems))
        if previous is None:
            return _unknown(reading.confidence, ("no_previous_state",))
        state = _follow(self._rules, previous, reading.tops)
        if state is None:
            return _unknown(reading.confidence, ("no_matching_move",))
        if self._rules.is_terminal(state):
            ui = UiState(UiKind.GAME_OVER, "game_over")
        elif state.to_move is self._me:
            ui = UiState(UiKind.PLAYABLE, "my_turn")
        else:
            ui = UiState(UiKind.WAITING, "opponent_turn")
        return Recognition(ui=ui, state=state, confidence=reading.confidence)


@dataclass(frozen=True)
class BoardReading:
    tops: dict[HexCoord, Piece]  # 見えている一番上の駒(画面の座標。(0,0) は左上のマス)
    confidence: float
    problems: tuple[str, ...]


def read_board(image: NDArray[np.uint8]) -> BoardReading:
    tiles = find_tiles(image)
    if not tiles:
        return BoardReading({}, 0.0, ())
    placed = to_axial(tiles)
    if placed is None:
        return BoardReading({}, 0.0, ("grid_mismatch",))
    tops: dict[HexCoord, Piece] = {}
    problems: list[str] = []
    confidence = 1.0
    for at, tile in placed.items():
        reading = classify(tile.glyph_hsv)
        confidence = min(confidence, reading.confidence)
        if reading.kind is None or reading.confidence < ELEMENT_MIN:
            problems.append(f"kind@{at.q},{at.r}")
            continue
        tops[at] = Piece(tile.side, reading.kind)
    if _hidden_ground(image, tiles) > HIDDEN_GROUND_MAX:
        problems.append("hidden_piece")
    return BoardReading(tops, confidence, tuple(problems))


def _hidden_ground(image: NDArray[np.uint8], tiles: list[Tile]) -> int:
    """マスで覆われていない地の画素のうち、マス1つ分の大きさの塊だけを数える。

    トースト(横長の帯)や影は、マスの形ではないので数えない。隠れた駒の地は、マスの形で見える。
    """
    cream, dark = ground_masks(image)
    covered = tile_hex_mask(image.shape[:2], tiles)
    left = ((cream | dark) & (1 - covered)).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(left, connectivity=8)
    total = 0
    for i in range(1, count):
        x0, y0, w, h, area = (int(v) for v in stats[i])
        if w <= 2 * TILE_R + 10 and h <= 2 * TILE_H:
            total += area
    return total


def _shifted(tops: dict[HexCoord, Piece]) -> dict[HexCoord, Piece]:
    """最小の q と r が 0 になるように平行移動する(盤の位置に依らない比較のため)。"""
    if not tops:
        return {}
    min_q = min(at.q for at in tops)
    min_r = min(at.r for at in tops)
    return {HexCoord(at.q - min_q, at.r - min_r): piece for at, piece in tops.items()}


def _tops_of(state: HiveState) -> dict[HexCoord, Piece]:
    tops: dict[HexCoord, Piece] = {}
    for at in state.occupied():
        top = state.top(at)
        if top is not None:
            tops[at] = top
    return tops


def _follow(
    rules: HiveRules, previous: HiveState, observed: dict[HexCoord, Piece]
) -> HiveState | None:
    target = _shifted(observed)
    if _shifted(_tops_of(previous)) == target:
        return previous
    for move in rules.legal_moves(previous):
        child = rules.apply(previous, move)
        if _shifted(_tops_of(child)) == target:
            return child
    return None


def _unknown(confidence: float, low: tuple[str, ...]) -> Recognition[HiveState]:
    return Recognition(
        ui=UiState(UiKind.UNKNOWN, "unknown"),
        state=None,
        confidence=confidence,
        low_confidence=low,
    )
