"""Monopoly の骨組み(計画3・フェーズ2)。設定の読み込み、プラグインの登録、未実装部品の明示的な停止。"""

from pathlib import Path

import pytest

from bglm.application.registry import PluginRegistry
from bglm.core.config import load_game_config
from bglm.plugins.monopoly.logic.moves import Buy, Roll

CONFIG = Path("config/monopoly.toml")


def test_config_loads_with_monopoly_target() -> None:
    config = load_game_config(CONFIG)

    assert config.game == "monopoly"
    assert config.target.kind == "android"
    assert config.target.serial == "355092380222016"
    assert config.runner.confidence_threshold == 0.75


def test_registry_loads_plugin_by_name() -> None:
    plugin = PluginRegistry().load("monopoly")

    assert plugin.name == "monopoly"


@pytest.mark.parametrize("method", ["recognizer", "rules", "strategy", "executor"])
def test_unimplemented_parts_stop_explicitly(method: str) -> None:
    plugin = PluginRegistry().load("monopoly")

    with pytest.raises(NotImplementedError):
        getattr(plugin, method)()


def test_moves_are_values() -> None:
    assert Buy("Baltic Avenue") == Buy("Baltic Avenue")
    assert Roll() == Roll()
