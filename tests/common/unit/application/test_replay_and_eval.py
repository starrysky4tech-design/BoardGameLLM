"""Replayer と EvalHarness、および実行の組み立て(wiring)のテスト。偽のゲームだけで動く。"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from tests.common.support.fake_game import FakeExecutor, FakeRules, FakeStrategy, frame

from bglm.application.evaluation import EvalError, EvalHarness
from bglm.application.replay import Replayer, ReplayError
from bglm.cli import wiring
from bglm.core.config import AndroidTarget, GameConfig
from bglm.core.models import (
    Frame,
    InputAction,
    Recognition,
    StopReason,
    UiKind,
    UiState,
    VlmProfile,
)
from bglm.core.protocols import GameIo
from bglm.infrastructure.run_logger import FsRunReader, PngStore


class PixelRecognizer:
    """画像の左上の画素値から状態を決める。同じ画像なら必ず同じ結果(再現できる認識)。"""

    def __init__(self, offset: int = 0) -> None:
        self._offset = offset

    def observe(self, io: GameIo, previous: int | None) -> Recognition[int]:
        value = int(io.capture().image[0, 0, 0])
        kind = UiKind.GAME_OVER if value >= 200 else UiKind.PLAYABLE
        return Recognition(UiState(kind, "main"), value + self._offset, 1.0)

    def debug_overlay(self, frame: Frame, result: Recognition[int]) -> Any:
        return frame.image


class PixelPlugin:
    name = "pixel"

    def __init__(self, offset: int = 0) -> None:
        self._offset = offset
        self._executor = FakeExecutor()

    def recognizer(self) -> PixelRecognizer:
        return PixelRecognizer(self._offset)

    def rules(self) -> FakeRules:
        return FakeRules()

    def strategy(self) -> FakeStrategy:
        return FakeStrategy()

    def executor(self) -> FakeExecutor:
        return self._executor

    def vlm_profile(self) -> VlmProfile | None:
        return None

    def describe_recognition(self, recognition: Recognition[int]) -> dict[str, Any]:
        if recognition.state is None:
            return {}
        return {"value": recognition.state, "cells[0]": "a", "cells[1]": "b"}


class SequenceSource:
    """決まった画像を順に返し、最後の画像は繰り返す。"""

    def __init__(self, values: list[int]) -> None:
        self._frames = [frame(v) for v in values]
        self._i = 0

    def capture(self) -> Frame:
        f = self._frames[min(self._i, len(self._frames) - 1)]
        self._i += 1
        return f


class RecordingDriver:
    def __init__(self) -> None:
        self.sent: list[InputAction] = []

    def perform(self, action: InputAction) -> None:
        self.sent.append(action)


CONFIG = GameConfig(game="pixel", target=AndroidTarget(serial="x"))


def _run(tmp_path: Path, dry_run: bool = False, values: list[int] | None = None) -> Any:
    driver = RecordingDriver()
    lines: list[str] = []
    summary = wiring.execute_run(
        plugin=PixelPlugin(),
        config=CONFIG,
        mode="auto",
        dry_run=dry_run,
        source=SequenceSource(values or [10, 60, 250]),
        driver=driver,
        runs_root=tmp_path,
        confirm=None,
        echo=lines.append,
        watch_keyboard=False,
        now=lambda: datetime(2026, 10, 30, 19, 0, 0),
        sleep=lambda _s: None,
    )
    return summary, driver, lines


def test_run_sends_input_and_prints_a_line_per_step(tmp_path: Path) -> None:
    summary, driver, lines = _run(tmp_path)
    assert summary.stop_reason is StopReason.GAME_OVER
    assert summary.run_id == "20261030-190000-pixel"
    assert len(driver.sent) == 2
    assert len(lines) == 3 and all("信頼度" in line for line in lines)


def test_dry_run_sends_nothing_but_still_records_the_actions(tmp_path: Path) -> None:
    summary, driver, _ = _run(tmp_path, dry_run=True)
    assert summary.stop_reason is StopReason.GAME_OVER
    assert driver.sent == []
    steps = FsRunReader(tmp_path).steps(summary.run_id)
    assert [len(s.actions) for s in steps] == [1, 1, 0]


def test_replay_of_a_saved_run_is_consistent(tmp_path: Path) -> None:
    summary, _, _ = _run(tmp_path)
    results = Replayer(PixelPlugin(), FsRunReader(tmp_path)).replay(summary.run_id)
    assert [r.step for r in results] == [1, 2, 3]
    assert all(r.consistent for r in results)
    assert results[0].move_matches is True and results[2].move_matches is None


def test_replay_detects_a_changed_recognizer(tmp_path: Path) -> None:
    summary, _, _ = _run(tmp_path)
    results = Replayer(PixelPlugin(offset=1), FsRunReader(tmp_path)).replay(summary.run_id, step=1)
    assert len(results) == 1
    assert not results[0].recognition_matches and not results[0].consistent


def test_replay_errors(tmp_path: Path) -> None:
    summary, _, _ = _run(tmp_path)
    replayer = Replayer(PixelPlugin(), FsRunReader(tmp_path))
    with pytest.raises(ReplayError):
        replayer.replay("no-such-run")
    with pytest.raises(ReplayError):
        replayer.replay(summary.run_id, step=99)


def test_stop_description_names_reason_image_and_replay_command(tmp_path: Path) -> None:
    summary, _, _ = _run(tmp_path)
    lines = wiring.describe_stop(summary, tmp_path)
    assert "game_over" in lines[0]
    assert any(line.startswith("画像: ") for line in lines)
    assert lines[-1] == f"再現: bglm replay {summary.run_id} --step 3"


def _harness(tmp_path: Path, plugin: Any = None) -> EvalHarness:
    return EvalHarness(plugin or PixelPlugin(), tmp_path / "eval", PngStore())


def _image(value: int) -> np.ndarray:
    return np.full((8, 8, 3), value, np.uint8)


def test_eval_groups_elements_and_lists_misses(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    ok = {"screen": "main", "elements": {"value": 10, "cells[0]": "a", "cells[1]": "b"}}
    bad = {"screen": "other", "elements": {"value": 99, "cells[0]": "a", "cells[1]": "x"}}
    harness.add_case(_image(10), "case_ok", ok)
    harness.add_case(_image(10), "case_bad", bad)

    report = harness.evaluate()

    assert report.cases == 2
    assert (report.hits["screen"], report.totals["screen"]) == (1, 2)
    assert (report.hits["value"], report.totals["value"]) == (1, 2)
    assert (report.hits["cells"], report.totals["cells"]) == (3, 4)  # 添字の前の名前で集計
    assert len(report.misses) == 3
    assert report.worst_rate == 0.5 and not report.passes(0.95)


def test_eval_passes_when_everything_matches(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    harness.add_case(_image(10), "a", {"screen": "main", "elements": {"value": 10}})
    assert harness.evaluate().passes(0.95)


def test_add_case_validates_id_label_and_duplicates(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    harness.add_case(_image(10), "a", {"screen": "main"})
    with pytest.raises(EvalError):
        harness.add_case(_image(10), "a", {"screen": "main"})  # 上書きしない
    with pytest.raises(EvalError):
        harness.add_case(_image(10), "../x", {"screen": "main"})
    with pytest.raises(EvalError):
        harness.add_case(_image(10), "b", {"elements": {}})
    label = json.loads((tmp_path / "eval" / "pixel" / "a.json").read_text(encoding="utf-8"))
    assert label == {"screen": "main"}


def test_eval_needs_cases_and_a_describing_plugin(tmp_path: Path) -> None:
    with pytest.raises(EvalError):
        _harness(tmp_path).evaluate()  # 空

    class NoDescribe:
        name = "none"

    with pytest.raises(EvalError):
        EvalHarness(NoDescribe(), tmp_path, PngStore())  # type: ignore[arg-type]
