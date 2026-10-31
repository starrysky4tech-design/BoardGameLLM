"""録画画像で、認識 → 思考 → 実行の一巡(--dry-run)と、保存ログからの再現・評価セットへの追加を確かめる。

録画(datasets/、Git管理外)が無い環境では飛ばす。
"""

import json
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import pytest
from typer.testing import CliRunner

from bglm.application.registry import PluginRegistry
from bglm.application.replay import Replayer
from bglm.cli import wiring
from bglm.cli.main import app
from bglm.core.models import Frame, InputAction, StopReason
from bglm.infrastructure.run_logger import FsRunReader
from bglm.plugins.kahuna.vision.templates import DEFAULT_DIR

RECORDED = Path("datasets/eval/kahuna/session1_018.png")  # 自分の手番
pytestmark = pytest.mark.skipif(
    not RECORDED.exists() or not DEFAULT_DIR.exists(), reason="録画またはテンプレートが無い"
)


class FixedSource:
    def __init__(self, image: np.ndarray) -> None:
        self._image = image

    def capture(self) -> Frame:
        return Frame.from_image(self._image, datetime.now())


class Driver:
    def __init__(self) -> None:
        self.sent: list[InputAction] = []

    def perform(self, action: InputAction) -> None:
        self.sent.append(action)


def _dry_run(runs: Path) -> tuple[str, Driver, StopReason]:
    image = np.asarray(cv2.imdecode(np.fromfile(RECORDED, dtype=np.uint8), cv2.IMREAD_COLOR))
    driver = Driver()
    summary = wiring.execute_run(
        plugin=PluginRegistry().load("kahuna"),
        config=wiring.load_config("kahuna"),
        mode="auto",
        dry_run=True,
        source=FixedSource(image),
        driver=driver,
        runs_root=runs,
        confirm=None,
        echo=lambda _line: None,
        watch_keyboard=False,
        sleep=lambda _s: None,
    )
    return summary.run_id, driver, summary.stop_reason


def test_dry_run_reads_thinks_and_acts_without_sending_input(tmp_path: Path) -> None:
    run_id, driver, reason = _dry_run(tmp_path)
    assert driver.sent == []
    # 画面が変わらない(入力を送っていない)ので、操作の確認で止まる。誤操作にはならない
    assert reason in (StopReason.UNKNOWN_SCREEN, StopReason.NO_SCREEN_CHANGE)
    first = FsRunReader(tmp_path).steps(run_id)[0]
    assert first.recognition["ui"]["screen"] == "my_turn"
    assert first.chosen_move is not None and first.legal_move_count > 0
    assert first.actions, "実行しようとした操作が記録される"


def test_saved_log_is_replayed_to_the_same_recognition_and_move(tmp_path: Path) -> None:
    run_id, _, _ = _dry_run(tmp_path)
    plugin = PluginRegistry().load("kahuna")
    results = Replayer(plugin, FsRunReader(tmp_path)).replay(run_id, step=1)
    assert results[0].recognition_matches
    assert results[0].move_matches is True


def test_cli_replay_and_eval_add(tmp_path: Path) -> None:
    run_id, _, _ = _dry_run(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        app, ["replay", run_id, "--step", "1", "--game", "kahuna", "--runs-dir", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert "my_turn" in result.output

    eval_dir = tmp_path / "eval"
    args = ["eval", "add", run_id, "1", "--game", "kahuna", "--runs-dir", str(tmp_path)]
    added = runner.invoke(app, [*args, "--eval-dir", str(eval_dir), "--accept"])
    assert added.exit_code == 0, added.output
    label = json.loads((eval_dir / "kahuna" / f"{run_id}_000001.json").read_text(encoding="utf-8"))
    assert label["screen"] == "my_turn" and "hand" in label["elements"]

    evaluated = runner.invoke(app, ["eval", "--game", "kahuna", "--eval-dir", str(eval_dir)])
    assert evaluated.exit_code == 0, evaluated.output
    assert "最小 100.0%" in evaluated.output
