"""ゲームに依存しない実行ループ(AgentRunner)。

取得 → 認識 → 思考 → 操作 → 画面変化の確認 を繰り返し、判断できないことが起きたら
推測で操作せず止める。個別のゲームの知識は持たず、GamePlugin の Protocol にだけ依存する。
仕様の正本は docs/02 の「実行状態の遷移」と「エラーハンドリング」。
"""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol

from bglm.application.safety import SafetyGuard
from bglm.application.serialization import jsonable, recognition_to_dict
from bglm.core.config import RunnerConfig
from bglm.core.errors import InputRejectedError, SourceLostError, UserAbortError
from bglm.core.models import (
    Frame,
    InputAction,
    Recognition,
    RunSummary,
    StepRecord,
    StopReason,
    TimeBudget,
    UiKind,
    action_to_dict,
)
from bglm.core.protocols import ChangeDetector, GameIo, GamePlugin, RunSink

Mode = Literal["step", "auto"]


class RecordingGameIo(GameIo, Protocol):
    """1手ごとに、取得した画像と送った入力を取り出せる GameIo。"""

    def take_frames(self) -> list[Frame]: ...

    def take_actions(self) -> list[InputAction]: ...


@dataclass
class _Pending[S]:
    """実行済みで、次の観測で画面変化と予測との差異を確定させる手。"""

    record: StepRecord
    before: Frame  # 操作の対象にした画面
    predicted: S


class AgentRunner[S, M]:
    def __init__(
        self,
        *,
        plugin: GamePlugin[S, M],
        io: RecordingGameIo,
        detector: ChangeDetector,
        sink: RunSink,
        guard: SafetyGuard,
        config: RunnerConfig,
        run_id: str,
        mode: Mode,
        confirm: Callable[[M], bool] | None = None,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = datetime.now,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if mode == "step" and confirm is None:
            raise ValueError("step モードには confirm(人の承認)が必要")
        self._plugin = plugin
        self._recognizer = plugin.recognizer()
        self._rules = plugin.rules()
        self._strategy = plugin.strategy()
        self._executor = plugin.executor()
        self._io = io
        self._detector = detector
        self._sink = sink
        self._guard = guard
        self._config = config
        self._run_id = run_id
        self._mode = mode
        self._confirm = confirm
        self._clock = clock
        self._now = now
        self._sleep = sleep

        self._steps_done = 0
        self._previous: S | None = None
        self._pending: _Pending[S] | None = None
        self._repeated = 0
        self._unchanged = 0
        self._waited_sec = 0.0
        self._result: str | None = None

    def run(self) -> RunSummary:
        self._sink.start()
        started_at = self._now()
        try:
            reason = self._loop()
        finally:
            # 次の観測が無いまま終わった手は、画面変化を確認できていない(screen_changed=False)
            self._save_pending(diff=None, changed=False)
        summary = RunSummary(
            run_id=self._run_id,
            game=self._plugin.name,
            mode=self._mode,
            started_at=started_at,
            ended_at=self._now(),
            stop_reason=reason,
            result=self._result,
            steps=self._steps_done,
        )
        self._sink.save_summary(summary)
        return summary

    def _loop(self) -> StopReason:
        try:
            while True:
                reason = self._iterate()
                if reason is not None:
                    return reason
        except UserAbortError:
            self._save_stop_record(chosen=None)
            return StopReason.USER_ABORT
        except (SourceLostError, InputRejectedError):
            self._save_stop_record(chosen=None)
            return StopReason.SOURCE_LOST

    def _iterate(self) -> StopReason | None:
        if self._guard.abort_requested():
            return StopReason.USER_ABORT
        if self._steps_done >= self._config.step_limit:
            return StopReason.STEP_LIMIT

        started = self._clock()
        recognition = self._recognizer.observe(self._io, self._previous)
        recognize_ms = self._ms_since(started)
        frames = self._io.take_frames()

        self._flush_pending(frames, recognition)

        kind = recognition.ui.kind
        if kind is UiKind.WAITING:
            self._waited_sec += self._config.wait_poll_sec
            reason = self._guard.check_progress(
                steps_done=self._steps_done, repeated=0, unchanged=0, waited_sec=self._waited_sec
            )
            if reason is not None:
                self._save_stop_record(frames, recognition)
                return reason
            self._sleep(self._config.wait_poll_sec)
            return None
        self._waited_sec = 0.0

        if kind is UiKind.GAME_OVER:
            if recognition.state is not None:
                self._result = self._rules.outcome(recognition.state)
            self._save_stop_record(frames, recognition)
            return StopReason.GAME_OVER

        reason = self._guard.check_ui(recognition)
        if reason is not None:
            self._save_stop_record(frames, recognition)
            return reason

        state = recognition.state
        assert state is not None  # check_ui が PLAYABLE の state=None を弾いている
        self._repeated = self._repeated + 1 if state == self._previous else 1
        reason = self._guard.check_progress(
            steps_done=self._steps_done,
            repeated=self._repeated,
            unchanged=self._unchanged,
            waited_sec=0.0,
        )
        if reason is not None:
            self._save_stop_record(frames, recognition)
            return reason
        self._previous = state

        legal = self._rules.legal_moves(state)
        if not legal:
            self._save_stop_record(frames, recognition)
            return StopReason.NO_LEGAL_MOVE

        think_started = self._clock()
        budget = TimeBudget(self._config.think_budget_sec, self._clock)
        move = self._strategy.choose(state, legal, budget)
        if move not in legal:
            raise ValueError(f"Strategy が合法手以外を返した: {move!r}")
        think_ms = self._ms_since(think_started)

        if self._mode == "step":
            assert self._confirm is not None
            if not self._confirm(move):
                self._save_stop_record(frames, recognition, chosen=move)
                return StopReason.USER_ABORT

        predicted = self._rules.apply(state, move)
        act_started = self._clock()
        try:
            result = self._executor.execute(self._io, state, move)
        except (UserAbortError, SourceLostError, InputRejectedError) as e:
            self._save_stop_record(
                [*frames, *self._io.take_frames()], recognition, chosen=move, legal_count=len(legal)
            )
            return (
                StopReason.USER_ABORT if isinstance(e, UserAbortError) else StopReason.SOURCE_LOST
            )
        act_ms = self._ms_since(act_started)

        step = self._steps_done + 1
        exec_frames = self._io.take_frames()
        actions = self._io.take_actions()
        record = StepRecord(
            run_id=self._run_id,
            step=step,
            frame_paths=self._sink.save_frames(step, [*frames, *exec_frames]),
            recognition=recognition_to_dict(recognition),
            legal_move_count=len(legal),
            chosen_move=jsonable(move),
            actions=[action_to_dict(a) for a in actions],
            predicted_diff=None,
            screen_changed=False,
            elapsed_ms={"recognize": recognize_ms, "think": think_ms, "act": act_ms},
        )
        if not result.success:
            self._sink.save_step(record)
            return StopReason.UNKNOWN_SCREEN
        self._steps_done = step
        self._pending = _Pending(record, before=frames[-1], predicted=predicted)
        return None

    def _flush_pending(self, frames: Sequence[Frame], recognition: Recognition[S]) -> None:
        """前の手の画面変化と予測との差異を確定して保存し、画面が変わらなかった連続回数を更新する。"""
        pending = self._pending
        if pending is None:
            return
        changed = True if not frames else self._detector.changed(pending.before, frames[0])
        self._unchanged = 0 if changed else self._unchanged + 1
        diff: dict[str, Any] | None = None
        if recognition.state is not None:
            diff = self._rules.diff(pending.predicted, recognition.state)
        self._save_pending(diff=diff, changed=changed)

    def _save_pending(self, *, diff: dict[str, Any] | None, changed: bool) -> None:
        pending = self._pending
        if pending is None:
            return
        pending.record.predicted_diff = jsonable(diff) if diff is not None else None
        pending.record.screen_changed = changed
        self._sink.save_step(pending.record)
        self._pending = None

    def _save_stop_record(
        self,
        frames: Sequence[Frame] | None = None,
        recognition: Recognition[S] | None = None,
        *,
        chosen: M | None = None,
        legal_count: int = 0,
    ) -> None:
        """止めた原因の画像とログを残す(操作は送らない)。"""
        step = self._steps_done + 1
        taken = list(frames) if frames is not None else self._io.take_frames()
        overlay = None
        if recognition is not None and taken:
            overlay = self._recognizer.debug_overlay(taken[-1], recognition)
        record = StepRecord(
            run_id=self._run_id,
            step=step,
            frame_paths=self._sink.save_frames(step, taken, overlay),
            recognition=recognition_to_dict(recognition) if recognition is not None else {},
            legal_move_count=legal_count,
            chosen_move=jsonable(chosen) if chosen is not None else None,
            actions=[action_to_dict(a) for a in self._io.take_actions()],
            predicted_diff=None,
            screen_changed=False,
        )
        self._sink.save_step(record)

    def _ms_since(self, started: float) -> int:
        return int((self._clock() - started) * 1000)
