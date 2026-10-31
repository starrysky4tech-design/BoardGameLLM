"""AgentRunner の実行ループ。全 StopReason の経路で、操作が送られる/送られないことを確かめる。"""

import pytest
from tests.common.support.fake_game import (
    ArrayEqualDetector,
    FakeClock,
    FakePlugin,
    MemorySink,
    build,
    distinct_frames,
    frame,
    playable,
    rec,
)

from bglm.application.runner import AgentRunner
from bglm.application.safety import AbortFlag, SafetyGuard
from bglm.core.config import RunnerConfig
from bglm.core.errors import InputRejectedError, SourceLostError, UserAbortError
from bglm.core.models import StopReason, UiKind

GAME_OVER = rec(UiKind.GAME_OVER, state=0)


class TestNormalRun:
    def test_plays_until_game_over_and_reports_the_outcome(self) -> None:
        h = build([playable(0), playable(1), playable(2), rec(UiKind.GAME_OVER, state=3)])

        summary = h.run()

        assert summary.stop_reason is StopReason.GAME_OVER
        assert summary.steps == 3
        assert summary.result == "win"
        assert summary.game == "fake"
        assert summary.mode == "auto"

    def test_sink_is_started_once_and_summary_saved_once(self) -> None:
        h = build([GAME_OVER])

        summary = h.run()

        assert h.sink.started == 1
        assert h.sink.summaries == [summary]

    def test_each_executed_step_is_recorded_in_order_with_its_actions(self) -> None:
        h = build([playable(0), playable(1), rec(UiKind.GAME_OVER, state=2)], taps=2)

        h.run()

        executed = h.sink.steps[:2]
        assert [s.step for s in executed] == [1, 2]
        assert [len(s.actions) for s in executed] == [2, 2]
        assert executed[0].chosen_move == {"type": "Go"}
        assert executed[0].legal_move_count == 1

    def test_correct_prediction_records_an_empty_diff_and_screen_change(self) -> None:
        h = build([playable(0), rec(UiKind.GAME_OVER, state=1)])

        h.run()

        first = h.sink.steps[0]
        assert first.predicted_diff == {}
        assert first.screen_changed is True

    def test_wrong_prediction_is_recorded_but_does_not_stop_the_run(self) -> None:
        h = build([playable(0), playable(5), rec(UiKind.GAME_OVER, state=6)])

        summary = h.run()

        assert h.sink.steps[0].predicted_diff == {"state": [1, 5]}
        assert summary.stop_reason is StopReason.GAME_OVER
        assert summary.steps == 2

    def test_previous_state_is_passed_to_the_recognizer(self) -> None:
        h = build([playable(0), playable(1), rec(UiKind.GAME_OVER, state=2)])

        h.run()

        assert h.plugin.recognizer().previous_seen == [None, 0, 1]

    def test_think_budget_comes_from_the_config(self) -> None:
        h = build([playable(0), GAME_OVER], config=RunnerConfig(think_budget_sec=3.0))

        h.run()

        assert h.plugin.strategy().budgets[0].remaining() == pytest.approx(3.0)

    def test_game_over_without_state_has_no_result(self) -> None:
        h = build([rec(UiKind.GAME_OVER, state=None)])

        assert h.run().result is None

    def test_game_over_is_accepted_even_with_low_confidence(self) -> None:
        h = build([rec(UiKind.GAME_OVER, state=1, confidence=0.1)])

        assert h.run().stop_reason is StopReason.GAME_OVER

    def test_final_screen_is_saved_with_a_debug_overlay(self) -> None:
        h = build([playable(0), GAME_OVER])

        h.run()

        assert (2, 1, True) in h.sink.saved_frames
        assert h.plugin.recognizer().overlays == 1


class TestStopsWithoutOperating:
    """画面を信用できないときは、1回も操作を送らずに止まる。"""

    @pytest.mark.parametrize(
        ("recognition", "reason"),
        [
            (playable(0, confidence=0.79), StopReason.LOW_CONFIDENCE),
            (rec(UiKind.PLAYABLE, state=None, confidence=1.0), StopReason.LOW_CONFIDENCE),
            (rec(UiKind.UNKNOWN, state=None), StopReason.UNKNOWN_SCREEN),
            (rec(UiKind.FORBIDDEN, state=None), StopReason.FORBIDDEN_SCREEN),
        ],
    )
    def test_first_observation_untrusted(self, recognition: object, reason: StopReason) -> None:
        h = build([recognition])  # type: ignore[list-item]

        summary = h.run()

        assert summary.stop_reason is reason
        assert summary.steps == 0
        assert h.sink.actions_sent == 0
        assert h.plugin.executor().calls == 0

    def test_cause_image_and_overlay_are_saved(self) -> None:
        h = build([rec(UiKind.UNKNOWN, state=None)])

        h.run()

        assert h.sink.saved_frames == [(1, 1, True)]
        assert h.sink.steps[0].recognition["ui"]["kind"] == "unknown"

    def test_confidence_exactly_at_the_threshold_is_trusted(self) -> None:
        h = build([playable(0, confidence=0.8), GAME_OVER])

        assert h.run().steps == 1

    def test_no_legal_move_stops_without_operating(self) -> None:
        h = build([playable(0)], no_moves_for=frozenset({0}))

        summary = h.run()

        assert summary.stop_reason is StopReason.NO_LEGAL_MOVE
        assert h.sink.actions_sent == 0
        assert h.sink.steps[0].legal_move_count == 0

    def test_step_mode_rejection_stops_without_operating(self) -> None:
        h = build([playable(0)], mode="step", approve=False)

        summary = h.run()

        assert summary.stop_reason is StopReason.USER_ABORT
        assert h.sink.actions_sent == 0
        assert h.sink.steps[0].chosen_move == {"type": "Go"}


class TestStopsAfterOperating:
    def test_unchanged_screen_is_retried_once_then_stops(self) -> None:
        same = [frame(10)] * 6
        h = build([playable(0), playable(0), playable(0)], frames=same)

        summary = h.run()

        assert summary.stop_reason is StopReason.NO_SCREEN_CHANGE
        assert h.sink.actions_sent == 2  # 最初の操作 + 1回だけのやり直し
        assert summary.steps == 2

    def test_a_change_after_one_unchanged_screen_resets_the_counter(self) -> None:
        frames = [frame(10), frame(10), frame(60), frame(60), frame(110), frame(160)]
        h = build(
            [playable(0), playable(0), playable(1), playable(1), rec(UiKind.GAME_OVER, state=2)],
            frames=frames,
        )

        assert h.run().stop_reason is StopReason.GAME_OVER

    def test_same_state_three_times_stops_even_if_the_screen_changes(self) -> None:
        h = build([playable(0), playable(0), playable(0)])

        summary = h.run()

        assert summary.stop_reason is StopReason.REPEATED_STATE
        assert h.sink.actions_sent == 2
        assert summary.steps == 2

    def test_step_limit_stops_before_observing_again(self) -> None:
        h = build([playable(0), playable(1), playable(2)], config=RunnerConfig(step_limit=2))

        summary = h.run()

        assert summary.stop_reason is StopReason.STEP_LIMIT
        assert summary.steps == 2
        assert len(h.plugin.recognizer().previous_seen) == 2
        assert h.sink.actions_sent == 2

    def test_step_limit_of_one_allows_exactly_one_step(self) -> None:
        h = build([playable(0), playable(1)], config=RunnerConfig(step_limit=1))

        summary = h.run()

        assert summary.steps == 1
        assert summary.stop_reason is StopReason.STEP_LIMIT

    def test_executor_reporting_failure_stops_as_unknown_screen(self) -> None:
        h = build([playable(0)])
        h.plugin.executor().fails = True

        summary = h.run()

        assert summary.stop_reason is StopReason.UNKNOWN_SCREEN
        assert summary.steps == 0
        assert len(h.sink.steps) == 1


class TestSourceLost:
    def test_observe_failure_stops_with_source_lost(self) -> None:
        h = build([playable(0), SourceLostError("端末が切断された")])

        summary = h.run()

        assert summary.stop_reason is StopReason.SOURCE_LOST
        assert summary.steps == 1

    def test_failure_on_the_first_observation(self) -> None:
        h = build([SourceLostError("x")])

        summary = h.run()

        assert summary.stop_reason is StopReason.SOURCE_LOST
        assert h.sink.actions_sent == 0

    @pytest.mark.parametrize("error", [SourceLostError("切断"), InputRejectedError("前面にない")])
    def test_executor_failure_stops_with_source_lost_and_saves_one_record(
        self, error: Exception
    ) -> None:
        h = build([playable(0)])
        h.plugin.executor().raises = error

        summary = h.run()

        assert summary.stop_reason is StopReason.SOURCE_LOST
        assert len(h.sink.steps) == 1
        assert h.sink.steps[0].chosen_move == {"type": "Go"}
        assert len(h.sink.steps[0].actions) == 1  # 失敗するまでに送った分は残る


class TestUserAbort:
    def test_abort_raised_while_recognizing_stops_with_user_abort(self) -> None:
        """MapScanner のように、認識の途中でスクロールの入力を送る場合でも緊急停止が効く。"""
        h = build([playable(0), UserAbortError("認識中の緊急停止")])

        summary = h.run()

        assert summary.stop_reason is StopReason.USER_ABORT
        assert summary.steps == 1

    def test_requested_before_start_never_touches_the_screen(self) -> None:
        h = build([])
        h.flag.request()

        summary = h.run()

        assert summary.stop_reason is StopReason.USER_ABORT
        assert h.plugin.recognizer().previous_seen == []
        assert h.sink.actions_sent == 0

    def test_requested_during_a_step_stops_before_the_next_observation(self) -> None:
        h = build([playable(0), playable(1)])
        h.plugin.executor().hook = lambda i: h.flag.request()

        summary = h.run()

        assert summary.stop_reason is StopReason.USER_ABORT
        assert summary.steps == 1
        assert len(h.plugin.recognizer().previous_seen) == 1

    def test_abort_raised_by_the_io_stops_with_user_abort(self) -> None:
        h = build([playable(0)])
        h.plugin.executor().raises = UserAbortError("緊急停止")

        summary = h.run()

        assert summary.stop_reason is StopReason.USER_ABORT
        assert len(h.sink.steps) == 1


class TestWaiting:
    def test_waiting_screens_are_polled_then_play_resumes(self) -> None:
        waiting = rec(UiKind.WAITING, state=None)
        h = build([playable(0), waiting, waiting, playable(1), rec(UiKind.GAME_OVER, state=2)])

        summary = h.run()

        assert summary.stop_reason is StopReason.GAME_OVER
        assert summary.steps == 2
        assert h.sleeps == [2.0, 2.0]

    def test_waiting_longer_than_the_limit_stops_without_operating(self) -> None:
        waiting = rec(UiKind.WAITING, state=None)
        h = build([waiting] * 4, config=RunnerConfig(wait_limit_sec=5.0, wait_poll_sec=2.0))

        summary = h.run()

        assert summary.stop_reason is StopReason.NO_SCREEN_CHANGE
        assert h.sleeps == [2.0, 2.0]  # 3回目(累計6秒>5秒)は待たずに止まる
        assert h.sink.actions_sent == 0

    def test_waiting_exactly_at_the_limit_is_still_allowed(self) -> None:
        waiting = rec(UiKind.WAITING, state=None)
        h = build(
            [waiting] * 3 + [GAME_OVER],
            config=RunnerConfig(wait_limit_sec=6.0, wait_poll_sec=2.0),
        )

        summary = h.run()

        assert summary.stop_reason is StopReason.GAME_OVER
        assert h.sleeps == [2.0, 2.0, 2.0]

    def test_wait_time_resets_after_a_playable_screen(self) -> None:
        waiting = rec(UiKind.WAITING, state=None)
        script = [waiting, waiting, playable(0), waiting, waiting, GAME_OVER]
        h = build(script, config=RunnerConfig(wait_limit_sec=5.0, wait_poll_sec=2.0))

        summary = h.run()

        assert summary.stop_reason is StopReason.GAME_OVER


class TestStepMode:
    def test_confirm_is_required(self) -> None:
        plugin = FakePlugin([])
        config = RunnerConfig()

        with pytest.raises(ValueError, match="confirm"):
            AgentRunner(
                plugin=plugin,
                io=build([]).io,
                detector=ArrayEqualDetector(),
                sink=MemorySink(),
                guard=SafetyGuard(config, AbortFlag()),
                config=config,
                run_id="r",
                mode="step",
                clock=FakeClock(),
            )

    def test_each_move_is_confirmed_before_it_is_executed(self) -> None:
        h = build([playable(0), playable(1), rec(UiKind.GAME_OVER, state=2)], mode="step")

        summary = h.run()

        assert len(h.confirmed) == 2
        assert summary.mode == "step"
        assert summary.steps == 2


class TestStrategyContract:
    def test_illegal_move_from_the_strategy_is_a_bug_not_a_stop(self) -> None:
        h = build([playable(0)])
        h.plugin.strategy().illegal = True

        with pytest.raises(ValueError, match="合法手以外"):
            h.run()

        assert h.sink.actions_sent == 0


def test_distinct_frames_are_all_different() -> None:
    frames = distinct_frames(5)
    detector = ArrayEqualDetector()

    assert all(detector.changed(a, b) for i, a in enumerate(frames) for b in frames[i + 1 :])
