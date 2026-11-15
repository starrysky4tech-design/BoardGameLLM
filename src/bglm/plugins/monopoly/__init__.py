"""Monopoly のプラグイン。`create_plugin()` を registry が動的に読み込む。

骨組みの段階。認識・ルール・思考・操作は、計画3(`.steering/20261102-monopoly-runtime`)の
フェーズ3〜5で差し込む。未実装の部品は、呼ばれたら NotImplementedError で止まる(推測で動かない)。
"""

from typing import Any

from bglm.core.models import Recognition
from bglm.plugins.monopoly.logic.moves import Move


class MonopolyPlugin:
    name = "monopoly"

    def recognizer(self) -> Any:
        raise NotImplementedError("Monopoly の recognizer は計画3のフェーズ5で作る")

    def rules(self) -> Any:
        raise NotImplementedError("Monopoly の rules(adapter)は計画3のフェーズ5で作る")

    def strategy(self) -> Any:
        raise NotImplementedError("Monopoly の strategy(adapter)は計画3のフェーズ5で作る")

    def executor(self) -> Any:
        raise NotImplementedError("Monopoly の executor は計画3のフェーズ3で作る")

    def describe_recognition(self, recognition: Recognition[Any]) -> dict[str, Any]:
        raise NotImplementedError("describe は計画3のフェーズ5で作る")

    def vlm_profile(self) -> None:
        return None  # VLM は使わない(CLAUDE.md「GPU」)


def create_plugin() -> MonopolyPlugin:
    return MonopolyPlugin()


__all__ = ["Move", "MonopolyPlugin", "create_plugin"]
