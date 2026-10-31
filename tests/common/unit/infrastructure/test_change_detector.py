from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from bglm.core.models import Frame, Rect
from bglm.infrastructure.change_detector import PixelRatioDetector
from bglm.infrastructure.run_logger import read_png

NOW = datetime(2026, 10, 30, 12, 0, 0)
PHASE0 = Path("datasets/raw/kahuna/feasibility")


def blank(height: int = 100, width: int = 200, value: int = 50) -> Frame:
    return Frame.from_image(np.full((height, width, 3), value, dtype=np.uint8), NOW)


def with_block(frame: Frame, top: int, left: int, size: int, value: int) -> Frame:
    image = frame.image.copy()
    image[top : top + size, left : left + size] = value
    return Frame.from_image(image, NOW)


class TestChanged:
    def test_identical_frames_are_unchanged(self) -> None:
        assert not PixelRatioDetector().changed(blank(), blank())

    def test_large_block_change_is_detected(self) -> None:
        before = blank()

        assert PixelRatioDetector().changed(before, with_block(before, 0, 0, 40, 255))

    def test_small_noise_below_pixel_delta_is_ignored(self) -> None:
        before = blank(value=50)
        after = blank(value=50 + 31)

        assert not PixelRatioDetector(pixel_delta=32).changed(before, after)

    def test_pixel_delta_boundary_counts_as_changed(self) -> None:
        before = blank(value=50)
        after = blank(value=50 + 32)

        assert PixelRatioDetector(pixel_delta=32).changed(before, after)

    def test_tiny_changed_area_below_min_ratio_is_ignored(self) -> None:
        before = blank(height=100, width=200)  # 20000画素
        after = with_block(before, 0, 0, 5, 255)  # 25画素 = 0.125%

        assert not PixelRatioDetector(min_ratio=0.005).changed(before, after)

    def test_ratio_exactly_at_min_ratio_is_unchanged(self) -> None:
        before = blank(height=100, width=200)
        after = with_block(before, 0, 0, 10, 255)  # 100画素 = ちょうど0.5%

        assert PixelRatioDetector(min_ratio=0.005).ratio(before, after) == pytest.approx(0.005)
        assert not PixelRatioDetector(min_ratio=0.005).changed(before, after)

    def test_change_outside_region_is_ignored(self) -> None:
        before = blank()
        after = with_block(before, 0, 0, 40, 255)
        region = Rect(left=100, top=0, width=100, height=100)

        assert not PixelRatioDetector().changed(before, after, region)

    def test_change_inside_region_is_detected(self) -> None:
        before = blank()
        after = with_block(before, 0, 100, 40, 255)
        region = Rect(left=100, top=0, width=100, height=100)

        assert PixelRatioDetector().changed(before, after, region)

    def test_region_catches_a_change_too_small_for_the_whole_frame(self) -> None:
        before = blank(height=100, width=200)
        after = with_block(before, 0, 0, 8, 255)  # 全体の0.32%
        region = Rect(left=0, top=0, width=20, height=20)

        assert not PixelRatioDetector().changed(before, after)
        assert PixelRatioDetector().changed(before, after, region)

    def test_empty_region_is_unchanged(self) -> None:
        before = blank()
        after = with_block(before, 0, 0, 40, 255)

        assert not PixelRatioDetector().changed(before, after, Rect(0, 0, 0, 0))

    def test_size_mismatch_raises(self) -> None:
        with pytest.raises(ValueError):
            PixelRatioDetector().changed(blank(100, 200), blank(100, 201))

    @pytest.mark.parametrize("kwargs", [{"pixel_delta": -1}, {"pixel_delta": 256}])
    def test_invalid_pixel_delta_raises(self, kwargs: dict[str, int]) -> None:
        with pytest.raises(ValueError):
            PixelRatioDetector(**kwargs)

    @pytest.mark.parametrize("min_ratio", [-0.1, 1.1])
    def test_invalid_min_ratio_raises(self, min_ratio: float) -> None:
        with pytest.raises(ValueError):
            PixelRatioDetector(min_ratio=min_ratio)


@pytest.mark.skipif(not PHASE0.exists(), reason="Phase 0 の撮影画像(Git管理外)が無い")
class TestWithPhase0Captures:
    """既定の閾値が、実機の画像で静止と変化を分けられることを確かめる。"""

    def frame(self, name: str) -> Frame:
        return Frame.from_image(read_png(PHASE0 / name), NOW)

    @pytest.mark.parametrize(
        ("a", "b"),
        [
            ("settle_1.png", "settle_2.png"),
            ("settle_3.png", "settle_4.png"),
            ("settle_5.png", "settle_6.png"),
        ],
    )
    def test_ambient_animation_is_not_a_change(self, a: str, b: str) -> None:
        assert not PixelRatioDetector().changed(self.frame(a), self.frame(b))

    @pytest.mark.parametrize(
        ("a", "b"),
        [
            ("11_hand_card_selected.png", "12_bridge_placed.png"),
            ("10_after_swipe_up.png", "11_hand_card_selected.png"),
            ("08_settled.png", "09_card_tapped.png"),
            ("04_after_play_tap_display.png", "05_match_start.png"),
        ],
    )
    def test_real_operations_are_changes(self, a: str, b: str) -> None:
        assert PixelRatioDetector().changed(self.frame(a), self.frame(b))
