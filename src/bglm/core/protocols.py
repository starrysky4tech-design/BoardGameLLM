"""共通基盤とプラグインの境界(Protocol)。仕様の正本は docs/02_FUNCTIONAL-DESIGN.md の「コンポーネント設計」。"""

from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import numpy as np
from numpy.typing import NDArray

from bglm.core.models import (
    ExecutionResult,
    Frame,
    InputAction,
    Reading,
    Recognition,
    Rect,
    RunSummary,
    StepRecord,
    TimeBudget,
    VlmProfile,
)


class ScreenSource(Protocol):
    def capture(self) -> Frame: ...


class InputDriver(Protocol):
    def perform(self, action: InputAction) -> None: ...


class GameIo(Protocol):
    """プラグインに渡す唯一の入出力の窓口。画像と入力の記録、緊急停止の確認を担う。"""

    def capture(self) -> Frame: ...

    def perform(self, action: InputAction) -> None: ...


class RunSink(Protocol):
    """実行ログの書き込み先。application は infrastructure の具象に依存しないため、この形で受け取る。"""

    def start(self) -> None: ...

    def save_frames(
        self,
        step: int,
        frames: Sequence[Frame],
        overlay: NDArray[np.uint8] | None = None,
    ) -> list[str]: ...

    def save_step(self, record: StepRecord) -> None: ...

    def save_summary(self, summary: RunSummary) -> None: ...


class RunReader(Protocol):
    """保存した実行ログの読み出し口。application は infrastructure の具象に依存しないため、この形で受け取る。"""

    def has_run(self, run_id: str) -> bool: ...

    def steps(self, run_id: str) -> list[StepRecord]:
        """手の順(step番号の昇順)。"""
        ...

    def frame(self, run_id: str, relative: str) -> Frame: ...


class ImageStore(Protocol):
    """画像ファイルの読み書き。"""

    def read(self, path: Path) -> NDArray[np.uint8]: ...

    def write(self, path: Path, image: NDArray[np.uint8]) -> None: ...


class ChangeDetector(Protocol):
    def changed(self, before: Frame, after: Frame, region: Rect | None = None) -> bool: ...


class ElementReader(Protocol):
    """1つの要素を読み取る手段(テンプレートマッチング、CNN、OCR、VLM)。"""

    def read(self, patch: NDArray[np.uint8]) -> Reading: ...


class Recognizer[S](Protocol):
    def observe(self, io: GameIo, previous: S | None) -> Recognition[S]: ...

    def debug_overlay(self, frame: Frame, result: Recognition[S]) -> NDArray[np.uint8]: ...


class Rules[S, M](Protocol):
    def legal_moves(self, state: S) -> list[M]: ...

    def apply(self, state: S, move: M) -> S:
        """手を打った後の予測盤面を返す。"""
        ...

    def is_terminal(self, state: S) -> bool: ...

    def outcome(self, state: S) -> str | None:
        """終了した盤面の勝敗("win" / "lose" / "draw")。判定できなければ None。"""
        ...

    def diff(self, predicted: S, actual: S) -> dict[str, Any]:
        """予測と実際の盤面の差異。差異が無ければ空。"""
        ...


class Strategy[S, M](Protocol):
    def choose(self, state: S, legal: Sequence[M], budget: TimeBudget) -> M:
        """合法手から1手を選ぶ。budget が尽きたらそれまでの最善手を返す。"""
        ...


class MoveExecutor[S, M](Protocol):
    def execute(self, io: GameIo, state: S, move: M) -> ExecutionResult: ...


@runtime_checkable
class GamePlugin[S, M](Protocol):
    """ゲームごとの認識・ルール・思考・操作をまとめた単位。"""

    name: str

    def recognizer(self) -> Recognizer[S]: ...

    def rules(self) -> Rules[S, M]: ...

    def strategy(self) -> Strategy[S, M]: ...

    def executor(self) -> MoveExecutor[S, M]: ...

    def vlm_profile(self) -> VlmProfile | None: ...


@runtime_checkable
class RecognitionDescriber[S](Protocol):
    """評価セットの正解と比べるために、認識結果を要素ごとの値に分解できるプラグイン。

    キーは要素名。同じ種類の要素が並ぶときは "sticks[3]" のように添字を付ける
    (正答率は、添字の前の名前ごとに集計する)。読み取れなかった要素は含めない。
    """

    def describe_recognition(self, recognition: Recognition[S]) -> dict[str, Any]: ...
