"""HoldDrag の値の検査と、ログへの保存・読み戻し。"""

import pytest

from bglm.core.models import HoldDrag, Point, action_from_dict, action_to_dict


def test_round_trips_through_log_dict() -> None:
    action = HoldDrag(Point(1257, 763), Point(1257, 300), hold_ms=600, steps=6, step_ms=40)

    assert action_from_dict(action_to_dict(action)) == action


@pytest.mark.parametrize(("hold_ms", "steps", "step_ms"), [(-1, 1, 10), (0, 0, 10), (600, 1, -5)])
def test_invalid_values_are_rejected(hold_ms: int, steps: int, step_ms: int) -> None:
    with pytest.raises(ValueError):
        HoldDrag(Point(0, 0), Point(0, 10), hold_ms=hold_ms, steps=steps, step_ms=step_ms)
