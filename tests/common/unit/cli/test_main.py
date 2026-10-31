"""CLI の引数と終了コード(実機・録画なしで動く範囲)。"""

from pathlib import Path

from typer.testing import CliRunner

from bglm.cli.main import app

runner = CliRunner()


def test_help_lists_every_command() -> None:
    output = runner.invoke(app, ["--help"]).output
    for name in ("run", "capture", "calibrate", "eval", "replay"):
        assert name in output


def test_run_rejects_an_unknown_mode() -> None:
    result = runner.invoke(app, ["run", "--game", "kahuna", "--mode", "fast"])
    assert result.exit_code == 2


def test_run_without_config_fails_before_touching_the_device(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["run", "--game", "kahuna", "--mode", "auto", "--config", str(tmp_path / "none.toml")]
    )
    assert result.exit_code == 2


def test_calibrate_is_not_needed_for_kahuna() -> None:
    result = runner.invoke(app, ["calibrate", "--game", "kahuna"])
    assert result.exit_code == 2


def test_replay_of_a_missing_run_fails(tmp_path: Path) -> None:
    result = runner.invoke(app, ["replay", "no-such-run", "--runs-dir", str(tmp_path)])
    assert result.exit_code == 2


def test_eval_add_needs_exactly_one_label_source(tmp_path: Path) -> None:
    result = runner.invoke(app, ["eval", "add", "r", "1", "--runs-dir", str(tmp_path)])
    assert result.exit_code == 2
