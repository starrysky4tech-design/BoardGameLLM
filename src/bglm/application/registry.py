"""設定のゲーム名からプラグインを読み込む。

application はプラグインの具象に依存しない(docs/04)。読み込みは文字列による動的 import で行い、
静的な依存を作らない。プラグインのパッケージは `create_plugin()` を公開する。
"""

import importlib
import re
from collections.abc import Callable
from typing import Any

from bglm.core.errors import PluginNotFoundError
from bglm.core.protocols import GamePlugin

# 任意のモジュールを import させないため、ゲーム名は小文字の識別子に限る
_NAME = re.compile(r"[a-z][a-z0-9_]*")

PluginFactory = Callable[[], GamePlugin[Any, Any]]


class PluginRegistry:
    def __init__(self, package: str = "bglm.plugins") -> None:
        self._package = package
        self._factories: dict[str, PluginFactory] = {}

    def register(self, name: str, factory: PluginFactory) -> None:
        """名前とファクトリを直接登録する(テストや、パッケージ外のプラグイン用)。"""
        self._check_name(name)
        self._factories[name] = factory

    def load(self, name: str) -> GamePlugin[Any, Any]:
        self._check_name(name)
        factory = self._factories.get(name) or self._import_factory(name)
        plugin = factory()
        if not isinstance(plugin, GamePlugin):
            raise PluginNotFoundError(f"プラグイン {name!r} が GamePlugin の形をしていない")
        if plugin.name != name:
            raise PluginNotFoundError(
                f"プラグイン名が一致しない: 要求={name!r} 実際={plugin.name!r}"
            )
        return plugin

    def _import_factory(self, name: str) -> PluginFactory:
        module_name = f"{self._package}.{name}"
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as e:
            # 対象のモジュールが無い場合だけ「見つからない」とする。中の import 失敗は隠さない
            if e.name == module_name or (e.name and module_name.startswith(e.name + ".")):
                raise PluginNotFoundError(
                    f"プラグイン {name!r} が見つからない: {module_name}"
                ) from e
            raise
        factory = getattr(module, "create_plugin", None)
        if not callable(factory):
            raise PluginNotFoundError(f"{module_name} に create_plugin() が無い")
        return factory  # type: ignore[no-any-return]

    @staticmethod
    def _check_name(name: str) -> None:
        if not _NAME.fullmatch(name):  # `$` は末尾の改行を許すため fullmatch を使う
            raise PluginNotFoundError(f"ゲーム名が不正: {name!r}(小文字の英数字と_のみ)")
