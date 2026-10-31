"""Hive のプラグインの登録と設定の確認。"""

from pathlib import Path

from bglm.application.registry import PluginRegistry
from bglm.core.config import load_game_config
from bglm.core.protocols import GamePlugin

CONFIG = Path("config/hive.toml")


def test_registry_loads_the_hive_plugin() -> None:
    plugin = PluginRegistry().load("hive")
    assert isinstance(plugin, GamePlugin)
    assert plugin.name == "hive"


def test_hive_config_is_valid() -> None:
    config = load_game_config(CONFIG)
    assert config.game == "hive"
    assert config.runner.think_budget_sec <= 10.0
