import dataclasses
from datetime import datetime

import numpy as np
import pytest

from bglm.core.models import (
    Drag,
    ExecutionResult,
    Frame,
    KeyPress,
    Point,
    Recognition,
    Rect,
    RunSummary,
    StepRecord,
    StopReason,
    Tap,
    TimeBudget,
    UiKind,
    UiState,
    action_from_dict,
    action_to_dict,
)

NOW = datetime(2026, 10, 30, 12, 0, 0)


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def make_step(**overrides: object) -> StepRecord:
    base: dict[str, object] = {
        "run_id": "20261030-120000-kahuna",
        "step": 12,
        "frame_paths": ["steps/000012/frame_01.png"],
        "recognition": {"ui": {"kind": "playable", "screen": "my_turn"}, "confidence": 0.97},
        "legal_move_count": 8,
        "chosen_move": {"type": "PlaceStick", "card": "LALE", "line": 14},
        "actions": [{"type": "Tap", "at": {"x": 512, "y": 880}}],
        "predicted_diff": None,
        "screen_changed": True,
        "elapsed_ms": {"capture": 420, "recognize": 310},
    }
    base.update(overrides)
    return StepRecord(**base)  # type: ignore[arg-type]


class TestFrame:
    def test_from_image_takes_size_from_shape(self) -> None:
        image = np.zeros((1080, 2432, 3), dtype=np.uint8)

        frame = Frame.from_image(image, NOW)

        assert (frame.width, frame.height) == (2432, 1080)

    def test_mismatched_size_raises(self) -> None:
        image = np.zeros((10, 20, 3), dtype=np.uint8)

        with pytest.raises(ValueError):
            Frame(image=image, width=10, height=20, captured_at=NOW)

    def test_grayscale_image_raises(self) -> None:
        image = np.zeros((10, 20), dtype=np.uint8)

        with pytest.raises(ValueError):
            Frame.from_image(image, NOW)

    def test_is_frozen(self) -> None:
        frame = Frame.from_image(np.zeros((2, 2, 3), dtype=np.uint8), NOW)

        with pytest.raises(dataclasses.FrozenInstanceError):
            frame.width = 5  # type: ignore[misc]


class TestRect:
    def test_zero_size_is_allowed(self) -> None:
        assert Rect(0, 0, 0, 0).width == 0

    def test_negative_size_raises(self) -> None:
        with pytest.raises(ValueError):
            Rect(0, 0, -1, 10)


class TestInputAction:
    @pytest.mark.parametrize(
        "action",
        [
            Tap(Point(1252, 486)),
            Drag(Point(1, 2), Point(3, 4), duration_ms=300),
            KeyPress("e"),
        ],
    )
    def test_roundtrip(self, action: Tap | Drag | KeyPress) -> None:
        assert action_from_dict(action_to_dict(action)) == action

    def test_unknown_type_raises(self) -> None:
        with pytest.raises(ValueError):
            action_from_dict({"type": "Pinch"})

    def test_drag_with_zero_duration_raises(self) -> None:
        with pytest.raises(ValueError):
            Drag(Point(0, 0), Point(1, 1), duration_ms=0)

    def test_is_frozen(self) -> None:
        tap = Tap(Point(1, 1))

        with pytest.raises(dataclasses.FrozenInstanceError):
            tap.at = Point(2, 2)  # type: ignore[misc]


class TestRecognition:
    ui = UiState(UiKind.PLAYABLE, "my_turn")

    @pytest.mark.parametrize("confidence", [0.0, 0.8, 1.0])
    def test_confidence_in_range_is_accepted(self, confidence: float) -> None:
        assert Recognition(self.ui, state=None, confidence=confidence).confidence == confidence

    @pytest.mark.parametrize("confidence", [-0.01, 1.01])
    def test_confidence_out_of_range_raises(self, confidence: float) -> None:
        with pytest.raises(ValueError):
            Recognition(self.ui, state=None, confidence=confidence)

    def test_low_confidence_defaults_to_empty(self) -> None:
        assert Recognition(self.ui, state=None, confidence=1.0).low_confidence == ()


class TestTimeBudget:
    def test_remaining_decreases_with_clock(self) -> None:
        clock = FakeClock()
        budget = TimeBudget(10.0, clock)

        clock.now += 4.0

        assert budget.remaining() == pytest.approx(6.0)
        assert not budget.expired()

    def test_expires_exactly_at_limit(self) -> None:
        clock = FakeClock()
        budget = TimeBudget(10.0, clock)

        clock.now += 10.0

        assert budget.expired()

    def test_remaining_never_negative(self) -> None:
        clock = FakeClock()
        budget = TimeBudget(1.0, clock)

        clock.now += 99.0

        assert budget.remaining() == 0.0

    @pytest.mark.parametrize("limit", [0.0, -1.0])
    def test_non_positive_limit_raises(self, limit: float) -> None:
        with pytest.raises(ValueError):
            TimeBudget(limit)


class TestStepRecord:
    def test_roundtrip(self) -> None:
        record = make_step()

        assert StepRecord.from_jsonable(record.to_jsonable()) == record

    def test_missing_elapsed_ms_defaults_to_empty(self) -> None:
        data = make_step().to_jsonable()
        del data["elapsed_ms"]

        assert StepRecord.from_jsonable(data).elapsed_ms == {}

    def test_step_below_one_raises(self) -> None:
        with pytest.raises(ValueError):
            make_step(step=0)

    def test_to_jsonable_does_not_alias_lists(self) -> None:
        record = make_step()

        record.to_jsonable()["frame_paths"].append("x.png")

        assert record.frame_paths == ["steps/000012/frame_01.png"]


class TestRunSummary:
    def make(self, **overrides: object) -> RunSummary:
        base: dict[str, object] = {
            "run_id": "r1",
            "game": "kahuna",
            "mode": "auto",
            "started_at": NOW,
            "ended_at": datetime(2026, 10, 30, 12, 30, 0),
            "stop_reason": StopReason.GAME_OVER,
            "result": "win",
            "steps": 42,
        }
        base.update(overrides)
        return RunSummary(**base)  # type: ignore[arg-type]

    def test_roundtrip(self) -> None:
        summary = self.make()

        assert RunSummary.from_jsonable(summary.to_jsonable()) == summary

    def test_every_stop_reason_survives_roundtrip(self) -> None:
        for reason in StopReason:
            summary = self.make(stop_reason=reason)
            assert RunSummary.from_jsonable(summary.to_jsonable()).stop_reason is reason

    @pytest.mark.parametrize("result", ["win", "lose", "draw", None])
    def test_valid_results(self, result: str | None) -> None:
        assert self.make(result=result).result == result

    def test_invalid_result_raises(self) -> None:
        with pytest.raises(ValueError):
            self.make(result="won")

    def test_invalid_mode_raises(self) -> None:
        with pytest.raises(ValueError):
            self.make(mode="fast")


class TestExecutionResult:
    def test_failure_carries_reason(self) -> None:
        result = ExecutionResult(success=False, reason="想定外の画面")

        assert not result.success
        assert result.actions == ()
