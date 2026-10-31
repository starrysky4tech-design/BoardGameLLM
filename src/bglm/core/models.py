"""共通のデータモデル。仕様の正本は docs/02_FUNCTIONAL-DESIGN.md の「データモデル定義」。

標準ライブラリとNumPyだけに依存する(依存ルールは docs/04)。
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class Point:
    """Frame座標(左上原点、ピクセル)。"""

    x: int
    y: int


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width < 0 or self.height < 0:
            raise ValueError(f"幅と高さは0以上: {self.width}x{self.height}")


@dataclass(frozen=True, eq=False)
class Frame:
    """取得した1枚の画面。ゲーム画面のみで、ウィンドウ枠を含まない。"""

    image: NDArray[np.uint8]  # BGR
    width: int
    height: int
    captured_at: datetime

    def __post_init__(self) -> None:
        if self.image.shape != (self.height, self.width, 3):
            raise ValueError(
                f"画像の形 {self.image.shape} が {self.height}x{self.width}x3 と一致しない"
            )

    @classmethod
    def from_image(cls, image: NDArray[np.uint8], captured_at: datetime) -> "Frame":
        height, width = image.shape[:2]
        return cls(image=image, width=width, height=height, captured_at=captured_at)


@dataclass(frozen=True)
class Tap:
    at: Point


@dataclass(frozen=True)
class Drag:
    start: Point
    end: Point
    duration_ms: int

    def __post_init__(self) -> None:
        if self.duration_ms <= 0:
            raise ValueError(f"duration_ms は1以上: {self.duration_ms}")


@dataclass(frozen=True)
class KeyPress:
    key: str  # 例: "e", "enter"。Androidでは使わない


InputAction = Tap | Drag | KeyPress


def action_to_dict(action: InputAction) -> dict[str, Any]:
    """ログに保存する形へ変換する。"""
    match action:
        case Tap(at=at):
            return {"type": "Tap", "at": {"x": at.x, "y": at.y}}
        case Drag(start=start, end=end, duration_ms=duration_ms):
            return {
                "type": "Drag",
                "start": {"x": start.x, "y": start.y},
                "end": {"x": end.x, "y": end.y},
                "duration_ms": duration_ms,
            }
        case KeyPress(key=key):
            return {"type": "KeyPress", "key": key}


def action_from_dict(data: dict[str, Any]) -> InputAction:
    """`action_to_dict` の逆変換。未知の種類は ValueError。"""
    kind = data.get("type")
    if kind == "Tap":
        return Tap(Point(data["at"]["x"], data["at"]["y"]))
    if kind == "Drag":
        s, e = data["start"], data["end"]
        return Drag(Point(s["x"], s["y"]), Point(e["x"], e["y"]), data["duration_ms"])
    if kind == "KeyPress":
        return KeyPress(data["key"])
    raise ValueError(f"未知の入力の種類: {kind!r}")


class UiKind(Enum):
    PLAYABLE = "playable"  # 自分が操作できる状態
    WAITING = "waiting"  # 相手の手番や演出の待ち
    GAME_OVER = "game_over"
    FORBIDDEN = "forbidden"  # オンライン対戦など、操作してはいけない画面
    UNKNOWN = "unknown"  # 想定外の画面


@dataclass(frozen=True)
class UiState:
    kind: UiKind
    screen: str  # プラグインが定義する画面名。例: "battle_forecast"


@dataclass(frozen=True)
class Recognition[S]:
    """認識の結果。

    confidence は読み取った要素の最小値。閾値未満のときは state を信用しない。
    """

    ui: UiState
    state: S | None  # PLAYABLE以外ではNoneでよい
    confidence: float
    low_confidence: tuple[str, ...] = ()  # 閾値未満だった要素の名前

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence は0.0〜1.0: {self.confidence}")


@dataclass(frozen=True)
class Reading:
    """ElementReader の読み取り結果。"""

    value: str
    confidence: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence は0.0〜1.0: {self.confidence}")


@dataclass(frozen=True)
class ExecutionResult:
    """MoveExecutor の実行結果。途中の画面が想定と違えば success=False で止める。"""

    success: bool
    reason: str | None = None
    actions: tuple[InputAction, ...] = ()


@dataclass(frozen=True)
class VlmProfile:
    """プラグインがVLMに渡す設定(任意)。"""

    adapter: str | None = None  # LoRAなどのアダプタ名
    prompt_prefix: str = ""


class TimeBudget:
    """思考時間の上限。時計を差し替えられる(テストを実時間に依存させないため)。"""

    def __init__(self, limit_sec: float, clock: Callable[[], float] = time.monotonic) -> None:
        if limit_sec <= 0:
            raise ValueError(f"limit_sec は0より大きい: {limit_sec}")
        self._clock = clock
        self._deadline = clock() + limit_sec

    def remaining(self) -> float:
        return max(0.0, self._deadline - self._clock())

    def expired(self) -> bool:
        return self.remaining() <= 0.0


class StopReason(Enum):
    GAME_OVER = "game_over"
    USER_ABORT = "user_abort"  # 緊急停止キー
    STEP_LIMIT = "step_limit"
    NO_SCREEN_CHANGE = "no_screen_change"
    REPEATED_STATE = "repeated_state"
    LOW_CONFIDENCE = "low_confidence"
    UNKNOWN_SCREEN = "unknown_screen"
    FORBIDDEN_SCREEN = "forbidden_screen"
    NO_LEGAL_MOVE = "no_legal_move"
    SOURCE_LOST = "source_lost"  # ウィンドウ消失、端末切断


@dataclass
class StepRecord:
    """1手の入出力の記録。保存形式は docs/02 の「データ保存形式」。"""

    run_id: str
    step: int  # 1始まりの連番
    frame_paths: list[str]
    recognition: dict[str, Any]
    legal_move_count: int
    chosen_move: dict[str, Any] | None
    actions: list[dict[str, Any]]
    predicted_diff: dict[str, Any] | None
    screen_changed: bool
    elapsed_ms: dict[str, int] = field(default_factory=dict)  # capture / recognize / think / act

    def __post_init__(self) -> None:
        if self.step < 1:
            raise ValueError(f"step は1以上: {self.step}")

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "step": self.step,
            "frame_paths": list(self.frame_paths),
            "recognition": self.recognition,
            "legal_move_count": self.legal_move_count,
            "chosen_move": self.chosen_move,
            "actions": self.actions,
            "predicted_diff": self.predicted_diff,
            "screen_changed": self.screen_changed,
            "elapsed_ms": dict(self.elapsed_ms),
        }

    @classmethod
    def from_jsonable(cls, data: dict[str, Any]) -> "StepRecord":
        return cls(
            run_id=data["run_id"],
            step=data["step"],
            frame_paths=list(data["frame_paths"]),
            recognition=data["recognition"],
            legal_move_count=data["legal_move_count"],
            chosen_move=data["chosen_move"],
            actions=list(data["actions"]),
            predicted_diff=data["predicted_diff"],
            screen_changed=data["screen_changed"],
            elapsed_ms=dict(data.get("elapsed_ms", {})),
        )


@dataclass
class RunSummary:
    run_id: str
    game: str
    mode: str  # "step" | "auto"
    started_at: datetime
    ended_at: datetime
    stop_reason: StopReason
    result: str | None  # "win" | "lose" | "draw" | None
    steps: int

    def __post_init__(self) -> None:
        if self.mode not in ("step", "auto"):
            raise ValueError(f"mode は step か auto: {self.mode!r}")
        if self.result not in (None, "win", "lose", "draw"):
            raise ValueError(f"result は win/lose/draw/None: {self.result!r}")

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "game": self.game,
            "mode": self.mode,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat(),
            "stop_reason": self.stop_reason.value,
            "result": self.result,
            "steps": self.steps,
        }

    @classmethod
    def from_jsonable(cls, data: dict[str, Any]) -> "RunSummary":
        return cls(
            run_id=data["run_id"],
            game=data["game"],
            mode=data["mode"],
            started_at=datetime.fromisoformat(data["started_at"]),
            ended_at=datetime.fromisoformat(data["ended_at"]),
            stop_reason=StopReason(data["stop_reason"]),
            result=data["result"],
            steps=data["steps"],
        )
