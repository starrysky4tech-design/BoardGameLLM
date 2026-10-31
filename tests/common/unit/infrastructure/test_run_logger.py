from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from bglm.core.models import Frame, RunSummary, StepRecord, StopReason
from bglm.infrastructure.run_logger import (
    RunLogger,
    load_frame,
    load_steps,
    load_summary,
    prune_runs,
    read_png,
    write_png,
)

NOW = datetime(2026, 10, 30, 12, 0, 0)


def frame(value: int = 10) -> Frame:
    image = np.full((8, 12, 3), value, dtype=np.uint8)
    image[2, 3] = (1, 2, 3)  # 色の順序(BGR)が保たれることを確かめるための画素
    return Frame.from_image(image, NOW)


def record(run_id: str, step: int, paths: list[str]) -> StepRecord:
    return StepRecord(
        run_id=run_id,
        step=step,
        frame_paths=paths,
        recognition={"confidence": 0.9},
        legal_move_count=3,
        chosen_move=None,
        actions=[],
        predicted_diff=None,
        screen_changed=True,
    )


def summary(run_id: str, ended: datetime, reason: StopReason = StopReason.GAME_OVER) -> RunSummary:
    return RunSummary(
        run_id=run_id,
        game="kahuna",
        mode="auto",
        started_at=ended - timedelta(minutes=5),
        ended_at=ended,
        stop_reason=reason,
        result=None,
        steps=1,
    )


def make_run(
    root: Path, run_id: str, ended: datetime | None, reason: StopReason, size: int
) -> None:
    """size バイトの画像データを持つ実行を作る。ended が None なら実行中(run.json なし)。"""
    logger = RunLogger(root, run_id)
    logger.start()
    (logger.run_dir / "blob.bin").write_bytes(b"x" * size)
    if ended is not None:
        logger.save_summary(summary(run_id, ended, reason))


class TestPng:
    def test_roundtrip_preserves_pixels(self, tmp_path: Path) -> None:
        image = frame().image

        write_png(tmp_path / "a.png", image)

        assert np.array_equal(read_png(tmp_path / "a.png"), image)

    def test_non_ascii_path_works(self, tmp_path: Path) -> None:
        path = tmp_path / "大戦略" / "画面.png"

        write_png(path, frame().image)

        assert read_png(path).shape == (8, 12, 3)

    def test_reading_invalid_file_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.png"
        bad.write_bytes(b"not a png")

        with pytest.raises(ValueError):
            read_png(bad)


class TestRunLogger:
    def test_frames_are_saved_with_relative_paths(self, tmp_path: Path) -> None:
        logger = RunLogger(tmp_path, "r1")
        logger.start()

        paths = logger.save_frames(7, [frame(1), frame(2)])

        assert paths == ["steps/000007/frame_01.png", "steps/000007/frame_02.png"]
        assert all((logger.run_dir / p).exists() for p in paths)

    def test_overlay_is_saved_when_given(self, tmp_path: Path) -> None:
        logger = RunLogger(tmp_path, "r1")
        logger.start()

        logger.save_frames(1, [frame()], overlay=frame(99).image)

        assert (logger.run_dir / "steps" / "000001" / "overlay.png").exists()

    def test_no_overlay_file_when_not_given(self, tmp_path: Path) -> None:
        logger = RunLogger(tmp_path, "r1")
        logger.start()

        logger.save_frames(1, [frame()])

        assert not (logger.run_dir / "steps" / "000001" / "overlay.png").exists()

    def test_zero_frames_returns_empty_list(self, tmp_path: Path) -> None:
        logger = RunLogger(tmp_path, "r1")
        logger.start()

        assert logger.save_frames(1, []) == []

    def test_steps_and_summary_roundtrip_in_step_order(self, tmp_path: Path) -> None:
        logger = RunLogger(tmp_path, "r1")
        logger.start()
        for step in (10, 2, 1):  # 順不同で書いても、読み戻しは step の昇順
            logger.save_step(record("r1", step, logger.save_frames(step, [frame()])))
        logger.save_summary(summary("r1", NOW))

        steps = load_steps(logger.run_dir)

        assert [s.step for s in steps] == [1, 2, 10]
        assert load_summary(logger.run_dir) == summary("r1", NOW)

    def test_saved_frame_can_be_loaded_back(self, tmp_path: Path) -> None:
        logger = RunLogger(tmp_path, "r1")
        logger.start()
        original = frame(33)
        [path] = logger.save_frames(1, [original])

        loaded = load_frame(logger.run_dir, path)

        assert np.array_equal(loaded.image, original.image)
        assert (loaded.width, loaded.height) == (12, 8)

    def test_starting_an_existing_run_raises(self, tmp_path: Path) -> None:
        RunLogger(tmp_path, "r1").start()

        with pytest.raises(FileExistsError):
            RunLogger(tmp_path, "r1").start()

    def test_japanese_directory_name_works(self, tmp_path: Path) -> None:
        logger = RunLogger(tmp_path / "実行ログ", "20261030-ハロー")
        logger.run_dir.parent.mkdir()
        logger.start()

        [path] = logger.save_frames(1, [frame()])

        assert load_frame(logger.run_dir, path).width == 12

    def test_load_steps_without_steps_dir_is_empty(self, tmp_path: Path) -> None:
        logger = RunLogger(tmp_path, "r1")
        logger.start()

        assert load_steps(logger.run_dir) == []


class TestPrune:
    def test_deletes_oldest_finished_runs_until_under_limit(self, tmp_path: Path) -> None:
        for i in range(3):
            make_run(tmp_path, f"r{i}", NOW + timedelta(hours=i), StopReason.GAME_OVER, 1000)

        deleted = prune_runs(tmp_path, limit_bytes=2500)

        assert deleted == ["r0"]
        assert sorted(p.name for p in tmp_path.iterdir()) == ["r1", "r2"]

    def test_does_nothing_when_under_limit(self, tmp_path: Path) -> None:
        make_run(tmp_path, "r0", NOW, StopReason.GAME_OVER, 1000)

        assert prune_runs(tmp_path, limit_bytes=10_000_000) == []

    def test_abnormal_runs_are_never_deleted(self, tmp_path: Path) -> None:
        make_run(tmp_path, "bad", NOW, StopReason.LOW_CONFIDENCE, 5000)
        make_run(tmp_path, "ok", NOW + timedelta(hours=1), StopReason.GAME_OVER, 1000)

        deleted = prune_runs(tmp_path, limit_bytes=1)

        assert deleted == ["ok"]
        assert (tmp_path / "bad").exists()

    def test_running_run_without_summary_is_kept(self, tmp_path: Path) -> None:
        make_run(tmp_path, "running", None, StopReason.GAME_OVER, 5000)

        assert prune_runs(tmp_path, limit_bytes=1) == []
        assert (tmp_path / "running").exists()

    def test_protected_run_is_kept(self, tmp_path: Path) -> None:
        make_run(tmp_path, "r0", NOW, StopReason.GAME_OVER, 5000)

        assert prune_runs(tmp_path, limit_bytes=1, protect=frozenset({"r0"})) == []

    def test_stops_when_only_protected_remain_over_limit(self, tmp_path: Path) -> None:
        make_run(tmp_path, "bad", NOW, StopReason.SOURCE_LOST, 5000)

        assert prune_runs(tmp_path, limit_bytes=1) == []

    def test_missing_root_returns_empty(self, tmp_path: Path) -> None:
        assert prune_runs(tmp_path / "none", limit_bytes=1) == []

    def test_limit_of_exact_total_deletes_nothing(self, tmp_path: Path) -> None:
        make_run(tmp_path, "r0", NOW, StopReason.GAME_OVER, 1000)
        total = sum(f.stat().st_size for f in tmp_path.rglob("*") if f.is_file())

        assert prune_runs(tmp_path, limit_bytes=total) == []
