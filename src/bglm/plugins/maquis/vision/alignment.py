"""画面の横ずれの補正。

実機(SHG11)は、起動のしかた(画面の回転の向き)によって、ゲームの描画が左右に 72px ずれることがある
(2026-11-15 に確認。以前の記録画面との位相相関が x=-72、y=0 の純粋な平行移動)。座標とテンプレートは
ずれの無い画面(`layout.py`)で作ってあるので、取得した画像を基準の位置へそろえ、タップはずれの分だけ動かす。

ずれは盤の絵(固定)の基準画像との位相相関で測る。盤が写らない画面(山札、確認ダイアログの一部など)では
測れないので、最後に測れた値を使う(同じ起動の間は変わらない)。測った値が大きすぎる、または縦にもずれて
いるときは、補正せず最後の値のままにする。
"""

from dataclasses import replace
from functools import cache
from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray

from bglm.core.models import Drag, Frame, HoldDrag, InputAction, Point, Tap
from bglm.core.protocols import GameIo
from bglm.toolkit.images import load_image

REFERENCE_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "templates" / "screens" / "align_map.png"
)
REFERENCE_BOX = (560, 220, 1700, 930)  # (左, 上, 右, 下)。基準画像を切り出した、盤の絵の領域
MAX_SHIFT = 150  # これを超えるずれは、測り間違いとみなす
RESPONSE_MIN = 0.3  # 位相相関の強さの下限(盤が写っていれば 0.6 以上)
VERTICAL_TOLERANCE = 2.0


@cache
def _reference() -> NDArray[np.float32] | None:
    image = load_image(REFERENCE_PATH, cv2.IMREAD_GRAYSCALE)
    return None if image is None else image.astype(np.float32)


def measure_shift(image: NDArray[np.uint8]) -> int | None:
    """基準の位置からの横ずれ(画素。左へずれていれば負)。盤が写っていなければ None。"""
    ref = _reference()
    if ref is None or image.shape[:2] != (1080, 2432):
        return None
    left, top, right, bottom = REFERENCE_BOX
    patch = cv2.cvtColor(image[top:bottom, left:right], cv2.COLOR_BGR2GRAY).astype(np.float32)
    (dx, dy), response = cv2.phaseCorrelate(ref, patch)
    if response < RESPONSE_MIN or abs(dy) > VERTICAL_TOLERANCE or abs(dx) > MAX_SHIFT:
        return None
    return round(dx)


def shifted_back(image: NDArray[np.uint8], dx: int) -> NDArray[np.uint8]:
    """横に dx ずれた画像を、基準の位置へ戻す。空いた端は端の色で埋める。"""
    if dx == 0:
        return image
    matrix = np.float32([[1, 0, -dx], [0, 1, 0]])  # type: ignore[call-overload]
    out = cv2.warpAffine(
        image, matrix, (image.shape[1], image.shape[0]), borderMode=cv2.BORDER_REPLICATE
    )
    return np.asarray(out, dtype=np.uint8)


class Alignment:
    """認識器と実行器で共有する、現在の横ずれ。"""

    def __init__(self) -> None:
        self.shift = 0

    def update(self, image: NDArray[np.uint8]) -> None:
        measured = measure_shift(image)
        if measured is not None:
            self.shift = measured

    def wrap(self, io: GameIo) -> "AlignedIo":
        return AlignedIo(io, self)


class AlignedIo:
    """撮影した画像を基準の位置へそろえ、タップをずれの分だけ動かす GameIo。"""

    def __init__(self, io: GameIo, alignment: Alignment) -> None:
        self._io = io
        self._alignment = alignment

    def capture(self) -> Frame:
        frame = self._io.capture()
        self._alignment.update(frame.image)
        image = shifted_back(frame.image, self._alignment.shift)
        return Frame.from_image(image, frame.captured_at)

    def perform(self, action: InputAction) -> None:
        dx = self._alignment.shift
        if dx == 0:
            self._io.perform(action)
            return
        match action:
            case Tap(at):
                self._io.perform(Tap(Point(at.x + dx, at.y)))
            case Drag() | HoldDrag():
                self._io.perform(
                    replace(
                        action,
                        start=Point(action.start.x + dx, action.start.y),
                        end=Point(action.end.x + dx, action.end.y),
                    )
                )
            case _:
                self._io.perform(action)
