"""実行の枠(guard.py)のテスト。adb の失敗と、操作の失敗で、必ず停止して記録されること。"""

import json
from pathlib import Path

import pytest

from bglm.core.errors import InputRejectedError, SourceLostError
from bglm.core.models import ExecutionResult
from bglm.plugins.monopoly.guard import guarded, open_log


def test_success_returns_none_and_logs_nothing() -> None:
    records: list[dict] = []

    stop = guarded(lambda: ExecutionResult(success=True), records.append, "roll")

    assert stop is None
    assert records == []


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (SourceLostError("adb 停止"), "source_lost"),
        (InputRejectedError("負の座標"), "input_rejected"),
    ],
)
def test_adb_errors_stop_and_are_recorded(error: Exception, reason: str) -> None:
    records: list[dict] = []

    def step() -> None:
        raise error

    stop = guarded(step, records.append, "end_turn")

    assert stop is not None and stop.reason == reason
    assert records == [{"step": "end_turn", "stop": reason, "detail": str(error)}]


def test_failed_execution_stops_with_reason() -> None:
    records: list[dict] = []

    stop = guarded(
        lambda: ExecutionResult(success=False, reason="ロールが反映されない"),
        records.append,
        "roll",
    )

    assert stop is not None and stop.reason == "execution_failed"
    assert records[0]["detail"] == "ロールが反映されない"


def test_open_log_writes_json_lines(tmp_path: Path) -> None:
    path = tmp_path / "runs" / "log.jsonl"
    write = open_log(path)

    write({"step": "roll", "stop": None})
    write({"step": "end", "stop": "source_lost"})

    lines = path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["step"] for line in lines] == ["roll", "end"]
