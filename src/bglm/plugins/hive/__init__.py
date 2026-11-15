"""Hive のプラグイン。`create_plugin()` を registry が動的に読み込む。

自分の色は黒(CPU戦で、先手の白と対局する)。設定の既定は config/hive.toml。
"""

from bglm.core.models import VlmProfile
from bglm.plugins.hive.logic.models import Color, HiveMove, HiveState
from bglm.plugins.hive.logic.rules import HiveRules
from bglm.plugins.hive.logic.strategy import HiveStrategy
from bglm.plugins.hive.vision.executor import HiveExecutor
from bglm.plugins.hive.vision.recognizer import HiveRecognizer
from bglm.plugins.hive.vision.wide import WideBoardRecognizer

ME = Color.BLACK


class HivePlugin:
    name = "hive"

    def recognizer(self) -> WideBoardRecognizer:
        return WideBoardRecognizer(HiveRecognizer(ME))

    def rules(self) -> HiveRules:
        return HiveRules()

    def strategy(self) -> HiveStrategy:
        return HiveStrategy()

    def executor(self) -> HiveExecutor:
        return HiveExecutor(ME)

    def vlm_profile(self) -> VlmProfile | None:
        return None  # VLM は使わない(盤面は色と形で読む)


def create_plugin() -> HivePlugin:
    return HivePlugin()


__all__ = ["HiveMove", "HivePlugin", "HiveState", "create_plugin"]
