"""実機の操作を、例外と想定外の画面から守る実行の枠(手順1)。

- adb の失敗(SourceLostError)、入力の拒否(InputRejectedError)は、例外のまま上げず、停止理由として記録する
- 停止は必ず記録する(JSON Lines)。推測で続けない
- 戦績・保存に影響する操作(Abandon、Save & Exit)は、ここでは扱わない
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bglm.core.errors import InputRejectedError, SourceLostError


@dataclass(frozen=True)
class Stop:
    reason: str
    detail: str


def guarded(
    step: Callable[[], Any],
    log: Callable[[dict[str, Any]], None],
    name: str,
) -> Stop | None:
    """1 手を実行する。例外なら停止理由を返し、ログに残す。成功なら None。"""
    try:
        result = step()
    except SourceLostError as error:
        stop = Stop("source_lost", str(error))
    except InputRejectedError as error:
        stop = Stop("input_rejected", str(error))
    else:
        if result is not None and not getattr(result, "success", True):
            stop = Stop("execution_failed", str(getattr(result, "reason", "")))
        else:
            return None
    log({"step": name, "stop": stop.reason, "detail": stop.detail})
    return stop


def open_log(path: Path) -> Callable[[dict[str, Any]], None]:
    path.parent.mkdir(parents=True, exist_ok=True)

    def write(record: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    return write
