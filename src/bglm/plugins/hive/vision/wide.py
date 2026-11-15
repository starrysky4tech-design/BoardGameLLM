"""盤が画面の幅を超えるときの、全体の読み取りと、寄せる操作(段階2)。

盤を中央・左寄せ・右寄せの3枚で取り、継ぎ合わせて全体を読む。タップの位置は、
中央の画面の座標で求める。見えないマスへ打つときは、寄せてから読み直す。
寄せる操作は、盤の外の木目から始める(駒を動かさないため)。
"""

import time
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from bglm.core.models import Drag, Frame, Point, Recognition
from bglm.core.protocols import GameIo
from bglm.plugins.hive.logic.models import HiveState
from bglm.plugins.hive.vision.grid import Tile, ground_masks
from bglm.plugins.hive.vision.recognizer import HiveRecognizer, read_tiles
from bglm.plugins.hive.vision.stitch import stitch_tiles

PAN_CHUNK = 160  # 1回のドラッグの長さ(画素)
PAN_MS = 500
PAN_WAIT_SEC = 1.5
SCREEN_W = 1080
VISIBLE_X = (40, SCREEN_W - 40)  # タップできる横の範囲(端の余白を除く)
VISIBLE_Y = (420, 2050)  # タップできる縦の範囲(盤の範囲の内側)

EDGE_COLUMNS = 20  # 画面の端からこの幅の列に、地の画素があれば盤が切れているとみなす
EDGE_GROUND_MIN = 100  # 端の列の地の画素の数の下限


@dataclass(frozen=True)
class WideView:
    """中央の画面を基準にした、盤全体のマス(中央の画面の座標)。"""

    tiles: list[Tile]
    centre: NDArray[np.uint8]


def _ground(image: NDArray[np.uint8]) -> NDArray[np.uint8]:
    cream, dark = ground_masks(image)
    return np.asarray(np.clip(cream + dark, 0, 1), dtype=np.uint8)


def board_clipped(image: NDArray[np.uint8]) -> int:
    """盤が画面の端で切れていれば、盤を寄せる向き(右で切れている +1、左で切れている -1)。0 は切れていない。"""
    ground = _ground(image)
    right = int(ground[:, -EDGE_COLUMNS:].sum())
    left = int(ground[:, :EDGE_COLUMNS].sum())
    if right >= EDGE_GROUND_MIN and right >= left:
        return 1
    if left >= EDGE_GROUND_MIN:
        return -1
    return 0


def empty_wood_start(image: NDArray[np.uint8], direction: int) -> Point | None:
    """ドラッグの開始点。駒やマスから離れた木目を選ぶ(マスの上から始めると、駒を動かしてしまうため)。"""
    ground = _ground(image)
    h, w = image.shape[:2]
    x = 120 if direction == -1 else w - 120
    for y in range(420, 1400, 40):
        x0, x1 = max(0, x - 60), min(w, x + 60)
        if int(ground[y - 60 : y + 60, x0:x1].sum()) == 0:
            return Point(x, y)
    return None


def pan_content(io: GameIo, dx: int, sleep: Callable[[float], None] = time.sleep) -> None:
    """盤の内容を横に dx 画素ずらす(右が正)。寄せる向きとは逆から、木目を引く。"""
    remaining = dx
    while abs(remaining) > 0:
        step = max(-PAN_CHUNK, min(PAN_CHUNK, remaining))
        image = io.capture().image
        start = empty_wood_start(image, direction=-1 if step > 0 else 1)
        if start is None:
            raise RuntimeError("寄せる木目が見つからない")
        io.perform(Drag(start, Point(start.x + step, start.y), PAN_MS))
        sleep(PAN_WAIT_SEC)
        remaining -= step


def wide_read(io: GameIo, sleep: Callable[[float], None] = time.sleep) -> WideView:
    """中央・左寄せ・右寄せの3枚を取り、継ぎ合わせる。最後は中央の位置に戻す。"""
    centre = io.capture().image
    pan_content(io, -PAN_CHUNK, sleep)
    left = io.capture().image
    pan_content(io, 2 * PAN_CHUNK, sleep)
    right = io.capture().image
    pan_content(io, -PAN_CHUNK, sleep)  # 中央へ戻す
    tiles = stitch_tiles([centre, left, right])
    return WideView(tiles=tiles, centre=centre)


def visible(x: float, y: float) -> bool:
    return VISIBLE_X[0] <= x <= VISIBLE_X[1] and VISIBLE_Y[0] <= y <= VISIBLE_Y[1]


class WideBoardRecognizer:
    """盤が画面より広いときは、3枚を継ぎ合わせて全体を読む(寄せる操作を含む)。収まっていれば1枚で読む。

    重ね描き(debug_overlay)は未実装のため、取得画像をそのまま返す。
    """

    def __init__(self, inner: HiveRecognizer, sleep: Callable[[float], None] = time.sleep) -> None:
        self._inner = inner
        self._sleep = sleep

    def observe(self, io: GameIo, previous: HiveState | None) -> Recognition[HiveState]:
        image = io.capture().image
        if board_clipped(image) == 0:
            return self._inner.recognize(image, previous)
        view = wide_read(io, self._sleep)
        return self._inner.recognize_reading(read_tiles(view.tiles), previous)

    def debug_overlay(self, frame: Frame, result: Recognition[HiveState]) -> NDArray[np.uint8]:
        return frame.image.copy()
