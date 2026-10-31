"""Kahuna のプラグイン。`create_plugin()` を registry が動的に読み込む。"""

from typing import Any

from bglm.core.models import Recognition, VlmProfile
from bglm.plugins.kahuna.logic.models import KahunaMove, KahunaState, default_board
from bglm.plugins.kahuna.logic.rules import KahunaRules
from bglm.plugins.kahuna.logic.strategy import KahunaStrategy
from bglm.plugins.kahuna.vision.describe import describe_recognition
from bglm.plugins.kahuna.vision.executor import KahunaExecutor
from bglm.plugins.kahuna.vision.recognizer import KahunaRecognizer
from bglm.plugins.kahuna.vision.templates import TemplateSet


class KahunaPlugin:
    name = "kahuna"

    def __init__(self) -> None:
        board = default_board()
        self._templates = TemplateSet.load(board=board)
        self._board = board

    def recognizer(self) -> KahunaRecognizer:
        return KahunaRecognizer(self._templates, self._board)

    def rules(self) -> KahunaRules:
        return KahunaRules(self._board)

    def strategy(self) -> KahunaStrategy:
        return KahunaStrategy(self._board)

    def executor(self) -> KahunaExecutor:
        return KahunaExecutor(self._templates, self._board)

    def describe_recognition(self, recognition: Recognition[KahunaState]) -> dict[str, Any]:
        return describe_recognition(recognition, self._board)

    def vlm_profile(self) -> VlmProfile | None:
        return None  # Phase 1 は VLM を使わない


def create_plugin() -> KahunaPlugin:
    return KahunaPlugin()


__all__ = ["KahunaMove", "KahunaPlugin", "KahunaState", "create_plugin"]
