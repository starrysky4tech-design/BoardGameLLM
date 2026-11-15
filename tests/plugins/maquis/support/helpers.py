"""Maquis のテスト用の補助。記録した実画面(Git管理外)を読む道具と、偽の入出力。

記録画面は `datasets/raw/maquis/feasibility/`。無い環境では、それを使うテストは飛ばす。
"""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from bglm.core.models import Frame, InputAction
from bglm.plugins.maquis.vision.deck_reader import DiscardRead
from bglm.toolkit.images import load_image

RAW = Path("datasets/raw/maquis/feasibility")


def frame_path(name: str) -> Path:
    return RAW / f"{name}.png"


def load_frame_image(name: str) -> NDArray[np.uint8]:
    image = load_image(frame_path(name))
    assert image is not None, name
    return image


class ScriptedIo:
    """撮影のたびに、決めた順で画像を返す偽の GameIo。入力は記録するだけ。"""

    def __init__(self, images: list[NDArray[np.uint8]]) -> None:
        self._images = images
        self._index = 0
        self.performed: list[InputAction] = []

    def capture(self) -> Frame:
        image = self._images[min(self._index, len(self._images) - 1)]
        self._index += 1
        return Frame.from_image(image, datetime(2026, 11, 11))

    def perform(self, action: InputAction) -> None:
        self.performed.append(action)


class FakeDeckReader:
    """山札の画面を開かず、決めたカードを返す。読み取りの回数を数える。"""

    def __init__(self, read: Callable[[], DiscardRead] | DiscardRead) -> None:
        self._read = read
        self.calls = 0

    def read_discard_top(self, io: object) -> DiscardRead:
        self.calls += 1
        return self._read() if callable(self._read) else self._read
