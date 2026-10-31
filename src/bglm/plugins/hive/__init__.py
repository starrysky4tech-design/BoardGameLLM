"""Hive のプラグイン。`create_plugin()` を registry が動的に読み込む。

自分の色は黒(CPU戦で、先手の白と対局する)。設定の既定は config/hive.toml。
"""

from typing import Any

import numpy as np
from numpy.typing import NDArray

from bglm.core.models import Frame, Recognition, VlmProfile
from bglm.plugins.hive.logic.models import Color, HiveMove, HiveState
from bglm.plugins.hive.logic.rules import HiveRules
from bglm.plugins.hive.logic.strategy import HiveStrategy
from bglm.plugins.hive.vision.executor import HiveExecutor
from bglm.plugins.hive.vision.recognizer import HiveRecognizer

ME = Color.BLACK


class HivePlugin:
    name = "hive"

    def recognizer(self) -> "HiveDebugRecognizer":
        return HiveDebugRecognizer(HiveRecognizer(ME))

    def rules(self) -> HiveRules:
        return HiveRules()

    def strategy(self) -> HiveStrategy:
        return HiveStrategy()

    def executor(self) -> HiveExecutor:
        return HiveExecutor(ME)

    def vlm_profile(self) -> VlmProfile | None:
        return None  # VLM は使わない(盤面は色と形で読む)


class HiveDebugRecognizer:
    """認識器の入れ物。重ね描きは未実装のため、取得画像をそのまま返す。"""

    def __init__(self, inner: HiveRecognizer) -> None:
        self._inner = inner

    def observe(self, io: Any, previous: HiveState | None) -> Recognition[HiveState]:
        return self._inner.observe(io, previous)

    def debug_overlay(self, frame: Frame, result: Recognition[HiveState]) -> NDArray[np.uint8]:
        return frame.image.copy()


def create_plugin() -> HivePlugin:
    return HivePlugin()


__all__ = ["HiveMove", "HivePlugin", "HiveState", "create_plugin"]
