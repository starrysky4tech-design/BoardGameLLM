"""描画の横ずれの補正のテスト。実画面(Git管理外)が無ければ、実画面を使うものは飛ばす。"""

import numpy as np
import pytest
from tests.plugins.maquis.support.helpers import ScriptedIo, frame_path, load_frame_image

from bglm.core.models import Point, Tap
from bglm.plugins.maquis.vision.alignment import Alignment, measure_shift, shifted_back
from bglm.plugins.maquis.vision.screens import ScreenKind, classify_screen


def shift_image(image: np.ndarray, dx: int) -> np.ndarray:  # type: ignore[type-arg]
    out = np.roll(image, dx, axis=1)
    return out  # type: ignore[no-any-return]


def need(name: str) -> None:
    if not frame_path(name).exists():
        pytest.skip(f"記録画面が無い(Git管理外): {name}")


def test_measures_a_synthetic_shift() -> None:
    need("game_001")
    base = load_frame_image("game_001")
    assert measure_shift(base) == 0
    assert measure_shift(shift_image(base, -72)) == -72
    assert measure_shift(shift_image(base, 40)) == 40


def test_blank_screen_has_no_shift() -> None:
    assert measure_shift(np.zeros((1080, 2432, 3), dtype=np.uint8)) is None


def test_shifted_screen_is_recognised_after_alignment() -> None:
    need("game_001")
    base = load_frame_image("game_001")
    moved = shift_image(base, -72)
    assert classify_screen(base) is ScreenKind.BOARD
    alignment = Alignment()
    alignment.update(moved)
    assert alignment.shift == -72
    assert classify_screen(shifted_back(moved, alignment.shift)) is ScreenKind.BOARD


def test_taps_are_moved_by_the_shift_and_other_screens_keep_the_last_value() -> None:
    need("game_001")
    moved = shift_image(load_frame_image("game_001"), -72)
    io = ScriptedIo([moved, np.zeros((1080, 2432, 3), dtype=np.uint8)])
    alignment = Alignment()
    aligned = alignment.wrap(io)  # type: ignore[arg-type]
    aligned.capture()
    aligned.capture()  # 盤が写らない画面でも、最後の値を使う
    aligned.perform(Tap(Point(1000, 500)))
    assert io.performed == [Tap(Point(928, 500))]


def test_five_agents_are_read_from_the_aligned_screen() -> None:
    # 2026-11-15 の通しで「0/5」を初めて観測した(ずれを補正して保存した画面)
    need("w_p5")
    from bglm.plugins.maquis.vision import layout
    from bglm.plugins.maquis.vision.digits import read_agent_counts
    from bglm.toolkit.images import crop

    counts, confidence = read_agent_counts(crop(load_frame_image("w_p5"), layout.AGENTS_BOX))
    assert counts == (0, 5)
    assert confidence > 0.8
