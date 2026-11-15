from collections.abc import Callable

import pytest

from bglm.toolkit.waiting import poll


class _Log:
    """probe と sleep の呼ばれた順を記録する。"""

    def __init__(self, values: list[int]) -> None:
        self._values = iter(values)
        self.events: list[str] = []

    def probe(self) -> int:
        value = next(self._values)
        self.events.append(f"probe:{value}")
        return value

    def sleep(self, sec: float) -> None:
        self.events.append(f"sleep:{sec}")


def _run(log: _Log, accept: Callable[[int], bool], **options: object) -> tuple[int, bool]:
    return poll(log.probe, accept, wait_sec=0.5, sleep=log.sleep, **options)  # type: ignore[arg-type]


def test_accepts_on_first_try_without_waiting() -> None:
    log = _Log([1])
    assert _run(log, lambda v: v == 1, tries=3) == (1, True)
    assert log.events == ["probe:1"]


def test_waits_between_tries_until_accepted() -> None:
    log = _Log([0, 0, 1])
    assert _run(log, lambda v: v == 1, tries=4) == (1, True)
    assert log.events == ["probe:0", "sleep:0.5", "probe:0", "sleep:0.5", "probe:1"]


def test_gives_up_after_tries_without_trailing_wait() -> None:
    log = _Log([0, 0])
    assert _run(log, lambda v: v == 1, tries=2) == (0, False)
    assert log.events == ["probe:0", "sleep:0.5", "probe:0"]


def test_wait_last_waits_after_the_final_failure() -> None:
    log = _Log([0, 0])
    assert _run(log, lambda v: v == 1, tries=2, wait_last=True) == (0, False)
    assert log.events == ["probe:0", "sleep:0.5", "probe:0", "sleep:0.5"]


def test_wait_first_waits_before_every_probe() -> None:
    log = _Log([0, 1])
    assert _run(log, lambda v: v == 1, tries=4, wait_first=True) == (1, True)
    assert log.events == ["sleep:0.5", "probe:0", "sleep:0.5", "probe:1"]


def test_wait_first_failure_has_no_extra_wait() -> None:
    log = _Log([0, 0])
    assert _run(log, lambda v: v == 1, tries=2, wait_first=True) == (0, False)
    assert log.events == ["sleep:0.5", "probe:0", "sleep:0.5", "probe:0"]


def test_tries_must_be_positive() -> None:
    with pytest.raises(ValueError):
        _run(_Log([]), lambda v: True, tries=0)
