"""設定のモデル。範囲外の値は読み込み時に検証して、起動前に止める(docs/05「パラメータ境界値の設計」)。

既定値の根拠は docs/02 の「既定値」。(仮)の値は計測後に置き換える。
"""

import tomllib
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from bglm.core.errors import ConfigError


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AndroidTarget(_Frozen):
    kind: Literal["android"] = "android"
    # 別の端末を操作する事故を防ぐため、シリアルは必須(既定値を持たない)
    serial: str = Field(min_length=1)
    # adb input の座標系は端末で異なる。SHG11(Android 16)は取得画像の座標(回転後)をそのまま使える
    input_space: Literal["display", "physical"] = "display"


class WindowTarget(_Frozen):
    kind: Literal["window"] = "window"
    # 題名が完全一致するウィンドウで特定する(VS Codeなど、題名に含むだけのウィンドウを除くため)
    title: str = Field(min_length=1)


Target = Annotated[AndroidTarget | WindowTarget, Field(discriminator="kind")]


class RunnerConfig(_Frozen):
    confidence_threshold: float = Field(default=0.8, ge=0.0, le=1.0)  # (仮)
    step_limit: int = Field(default=1000, ge=1)  # (仮)
    repeated_state_limit: int = Field(default=3, ge=1)  # (仮)
    wait_limit_sec: float = Field(default=300.0, gt=0.0)  # (仮)
    wait_poll_sec: float = Field(default=2.0, gt=0.0)  # (仮) 待機中に画面を取り直す間隔
    # 操作しても画面が変わらない回数の上限。2 = 1回だけやり直し、それでも変わらなければ停止
    unchanged_limit: int = Field(default=2, ge=1)
    abort_key: str = Field(default="f12", min_length=1)  # 緊急停止キー(pynput のキー名)
    # docs/05: 思考時間の上限は1秒以上。docs/01 の「1手10秒以内」以下に設定する
    think_budget_sec: float = Field(default=10.0, ge=1.0, le=10.0)  # (仮)
    log_limit_gib: float = Field(default=20.0, gt=0.0)  # (仮)


class GameConfig(_Frozen):
    game: str = Field(min_length=1)
    target: Target
    runner: RunnerConfig = RunnerConfig()


def load_game_config(path: Path) -> GameConfig:
    """TOMLから設定を読む。不正なら ConfigError。"""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        return GameConfig.model_validate(data)
    except (OSError, tomllib.TOMLDecodeError, ValidationError) as e:
        raise ConfigError(f"設定が不正: {path}: {e}") from e
