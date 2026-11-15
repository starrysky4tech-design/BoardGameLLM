"""Maquis のプラグイン。`create_plugin()` を registry が動的に読み込む。設定の既定は config/maquis.toml。

認識器と実行器は、画面の横ずれ(`Alignment`)を共有する。
状態(前の観測)は呼び出し側(runner)が持つ。

途中の対局から再開するには、環境変数 `MAQUIS_RESUME` に、止まる直前の実行ログの step.json を指定する
(例: `runs/<run_id>/steps/000003/step.json`)。その状態を出発点にして、画面と照合する。
"""

import os
from pathlib import Path

from bglm.core.models import VlmProfile
from bglm.plugins.maquis.logic.models import MaquisMove, MaquisState
from bglm.plugins.maquis.logic.resume import state_from_step_file
from bglm.plugins.maquis.logic.rules import MaquisRules
from bglm.plugins.maquis.logic.strategy import MaquisStrategy
from bglm.plugins.maquis.vision.alignment import Alignment
from bglm.plugins.maquis.vision.executor import MaquisExecutor
from bglm.plugins.maquis.vision.recognizer import MaquisRecognizer

RESUME_ENV = "MAQUIS_RESUME"


class MaquisPlugin:
    name = "maquis"

    def __init__(self) -> None:
        self._rules = MaquisRules()
        path = os.environ.get(RESUME_ENV)
        self._resume = state_from_step_file(Path(path)) if path else None
        self._alignment = Alignment()  # 認識器と実行器で、描画の横ずれを共有する

    def recognizer(self) -> MaquisRecognizer:
        return MaquisRecognizer(self._rules, alignment=self._alignment, resume=self._resume)

    def rules(self) -> MaquisRules:
        return self._rules

    def strategy(self) -> MaquisStrategy:
        return MaquisStrategy(self._rules)

    def executor(self) -> MaquisExecutor:
        return MaquisExecutor(self._rules, alignment=self._alignment)

    def vlm_profile(self) -> VlmProfile | None:
        return None  # VLM は使わない(盤は固定の座標・テンプレート・数字で読む)


def create_plugin() -> MaquisPlugin:
    return MaquisPlugin()


__all__ = ["MaquisMove", "MaquisPlugin", "MaquisState", "create_plugin"]
