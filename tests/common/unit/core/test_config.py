from pathlib import Path

import pytest

from bglm.core.config import AndroidTarget, GameConfig, RunnerConfig, load_game_config
from bglm.core.errors import ConfigError

ANDROID = """
game = "kahuna"

[target]
kind = "android"
serial = "355092380222016"
"""


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "game.toml"
    path.write_text(text, encoding="utf-8")
    return path


class TestLoad:
    def test_android_config_loads_with_defaults(self, tmp_path: Path) -> None:
        config = load_game_config(write(tmp_path, ANDROID))

        assert isinstance(config.target, AndroidTarget)
        assert config.target.serial == "355092380222016"
        assert config.target.input_space == "display"
        assert config.runner == RunnerConfig()

    def test_window_config_loads(self, tmp_path: Path) -> None:
        text = 'game = "ssb2"\n[target]\nkind = "window"\ntitle = "大戦略SSB2"\n'

        config = load_game_config(write(tmp_path, text))

        assert config.target.kind == "window"

    def test_missing_serial_raises(self, tmp_path: Path) -> None:
        text = 'game = "kahuna"\n[target]\nkind = "android"\n'

        with pytest.raises(ConfigError):
            load_game_config(write(tmp_path, text))

    def test_empty_serial_raises(self, tmp_path: Path) -> None:
        text = 'game = "kahuna"\n[target]\nkind = "android"\nserial = ""\n'

        with pytest.raises(ConfigError):
            load_game_config(write(tmp_path, text))

    def test_unknown_key_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError):
            load_game_config(write(tmp_path, ANDROID + "typo = 1\n"))

    def test_invalid_toml_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError):
            load_game_config(write(tmp_path, "game = = ="))

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError):
            load_game_config(tmp_path / "none.toml")


class TestRunnerBounds:
    @pytest.mark.parametrize("value", [0.0, 0.8, 1.0])
    def test_confidence_threshold_in_range(self, value: float) -> None:
        assert RunnerConfig(confidence_threshold=value).confidence_threshold == value

    @pytest.mark.parametrize("value", [-0.1, 1.1])
    def test_confidence_threshold_out_of_range_raises(self, value: float) -> None:
        with pytest.raises(ValueError):
            RunnerConfig(confidence_threshold=value)

    def test_step_limit_zero_raises(self) -> None:
        with pytest.raises(ValueError):
            RunnerConfig(step_limit=0)

    def test_step_limit_one_is_allowed(self) -> None:
        assert RunnerConfig(step_limit=1).step_limit == 1

    @pytest.mark.parametrize("value", [0.99, 10.01])
    def test_think_budget_outside_one_to_ten_raises(self, value: float) -> None:
        with pytest.raises(ValueError):
            RunnerConfig(think_budget_sec=value)

    @pytest.mark.parametrize("value", [1.0, 10.0])
    def test_think_budget_boundaries_are_allowed(self, value: float) -> None:
        assert RunnerConfig(think_budget_sec=value).think_budget_sec == value

    def test_non_positive_wait_limit_raises(self) -> None:
        with pytest.raises(ValueError):
            RunnerConfig(wait_limit_sec=0.0)

    def test_config_is_frozen(self) -> None:
        config = GameConfig(game="kahuna", target=AndroidTarget(serial="x"))

        with pytest.raises(ValueError):
            config.game = "other"  # type: ignore[misc]
