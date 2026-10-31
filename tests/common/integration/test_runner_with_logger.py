"""実行ループと実際のログ保存(RunLogger)をつなげて、書き出したログを読み戻せることを確かめる。"""

from pathlib import Path

import numpy as np
import pytest
from tests.common.support.fake_game import build, distinct_frames, playable, rec

from bglm.core.models import StopReason, UiKind, action_from_dict
from bglm.core.protocols import RunSink
from bglm.infrastructure.run_logger import (
    RunLogger,
    load_frame,
    load_steps,
    load_summary,
)


def test_run_log_can_be_read_back(tmp_path: Path) -> None:
    sink: RunSink = RunLogger(tmp_path, "run-1")
    frames = distinct_frames(4)
    h = build(
        [playable(0), playable(1), rec(UiKind.GAME_OVER, state=2)],
        frames=frames,
        sink=sink,
        taps=2,
    )

    summary = h.run()

    run_dir = tmp_path / "run-1"
    assert load_summary(run_dir) == summary
    steps = load_steps(run_dir)
    assert [s.step for s in steps] == [1, 2, 3]  # 実行した2手 + 終了画面
    assert steps[0].chosen_move == {"type": "Go"}
    assert steps[0].recognition["state"] == 0
    assert [action_from_dict(a) for a in steps[0].actions] == [
        action_from_dict({"type": "Tap", "at": {"x": 1, "y": 0}}),
        action_from_dict({"type": "Tap", "at": {"x": 1, "y": 1}}),
    ]
    assert np.array_equal(load_frame(run_dir, steps[0].frame_paths[0]).image, frames[0].image)
    assert (run_dir / "steps" / "000003" / "overlay.png").exists()


def test_stopped_run_keeps_the_cause_image(tmp_path: Path) -> None:
    h = build(
        [playable(0), rec(UiKind.UNKNOWN, state=None)],
        sink=RunLogger(tmp_path, "run-1"),
    )

    summary = h.run()

    assert summary.stop_reason is StopReason.UNKNOWN_SCREEN
    steps = load_steps(tmp_path / "run-1")
    assert steps[-1].recognition["ui"]["kind"] == "unknown"
    assert steps[-1].frame_paths == ["steps/000002/frame_01.png"]


def test_existing_run_id_is_never_overwritten(tmp_path: Path) -> None:
    RunLogger(tmp_path, "run-1").start()
    h = build([rec(UiKind.GAME_OVER, state=0)], sink=RunLogger(tmp_path, "run-1"))

    with pytest.raises(FileExistsError):
        h.run()
