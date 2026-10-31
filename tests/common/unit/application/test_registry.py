from pathlib import Path
from typing import Any

import pytest
from tests.common.support.fake_game import FakePlugin

from bglm.application.registry import PluginRegistry
from bglm.core.errors import PluginNotFoundError

PLUGIN_SOURCE = """
from tests.common.support.fake_game import FakePlugin


class _Plugin(FakePlugin):
    name = "{name}"


def create_plugin():
    return _Plugin([])
"""


def make_package(root: Path, files: dict[str, str]) -> None:
    for relative, text in files.items():
        path = root / "fakeplugins" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


@pytest.fixture
def registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> PluginRegistry:
    make_package(
        tmp_path,
        {
            "__init__.py": "",
            "alpha/__init__.py": PLUGIN_SOURCE.format(name="alpha"),
            "mismatch/__init__.py": PLUGIN_SOURCE.format(name="other"),
            "nofactory/__init__.py": "x = 1\n",
            "notplugin/__init__.py": "def create_plugin():\n    return object()\n",
            "brokendep/__init__.py": "import a_package_that_does_not_exist_anywhere\n",
        },
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    return PluginRegistry(package="fakeplugins")


class TestLoad:
    def test_loads_a_plugin_by_name(self, registry: PluginRegistry) -> None:
        plugin = registry.load("alpha")

        assert plugin.name == "alpha"

    def test_registered_factory_takes_precedence(self, registry: PluginRegistry) -> None:
        class Registered(FakePlugin):
            name = "alpha"

        registry.register("alpha", lambda: Registered([]))

        assert isinstance(registry.load("alpha"), Registered)

    def test_registered_plugin_does_not_need_a_module(self) -> None:
        registry = PluginRegistry(package="nonexistent_package")
        registry.register("fake", lambda: FakePlugin([]))

        assert registry.load("fake").name == "fake"

    def test_missing_plugin_raises(self, registry: PluginRegistry) -> None:
        with pytest.raises(PluginNotFoundError, match="見つからない"):
            registry.load("beta")

    def test_name_mismatch_raises(self, registry: PluginRegistry) -> None:
        with pytest.raises(PluginNotFoundError, match="一致しない"):
            registry.load("mismatch")

    def test_module_without_factory_raises(self, registry: PluginRegistry) -> None:
        with pytest.raises(PluginNotFoundError, match="create_plugin"):
            registry.load("nofactory")

    def test_factory_returning_a_non_plugin_raises(self, registry: PluginRegistry) -> None:
        with pytest.raises(PluginNotFoundError, match="GamePlugin"):
            registry.load("notplugin")

    def test_import_error_inside_the_plugin_is_not_hidden(self, registry: PluginRegistry) -> None:
        """プラグインの中の import 失敗を「見つからない」にすり替えない。"""
        with pytest.raises(ModuleNotFoundError, match="a_package_that_does_not_exist_anywhere"):
            registry.load("brokendep")


class TestNameValidation:
    @pytest.mark.parametrize(
        "name",
        ["", "Kahuna", "1abc", "a.b", "../x", "a-b", "a b", "os.path", "kahuna\n"],
    )
    def test_invalid_names_are_rejected_before_any_import(self, name: str) -> None:
        with pytest.raises(PluginNotFoundError, match="不正"):
            PluginRegistry().load(name)

    @pytest.mark.parametrize("name", ["kahuna", "ssb2", "a", "game_2"])
    def test_valid_names_pass_validation(self, name: str) -> None:
        registry = PluginRegistry(package="nonexistent_package")

        with pytest.raises(PluginNotFoundError, match="見つからない"):
            registry.load(name)

    def test_register_validates_the_name_too(self) -> None:
        factory: Any = lambda: FakePlugin([])  # noqa: E731

        with pytest.raises(PluginNotFoundError):
            PluginRegistry().register("../x", factory)
