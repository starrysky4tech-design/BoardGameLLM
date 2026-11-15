"""盤を寄せた画面の継ぎ合わせ。模擬の画面(木目つき)で、画面の幅を超える盤を読めることを確かめる。"""

import math

import cv2
import numpy as np
from numpy.typing import NDArray
from tests.plugins.hive.support.helpers import B, W, state
from tests.plugins.hive.support.render import _glyph_bgr

from bglm.plugins.hive.logic.models import Color, HexCoord, Kind, Piece
from bglm.plugins.hive.vision.grid import TILE_H, TILE_R, find_tiles
from bglm.plugins.hive.vision.recognizer import read_tiles
from bglm.plugins.hive.vision.stitch import measure_shift, read_stitched

W_CANVAS, H_CANVAS = 1700, 2432
SCREEN_W = 1080
PAN = 160  # 寄せる量(画素)。内容は左へ寄るほど、窓は右へ動く


def _scene(tops: dict[HexCoord, Piece], origin: tuple[float, float]) -> NDArray[np.uint8]:
    """木目つきの背景に、駒を描いた大きな画像(画面より広い)。"""
    rng = np.random.default_rng(7)
    base = rng.integers(120, 200, size=(H_CANVAS, W_CANVAS), dtype=np.uint8)
    canvas = cv2.cvtColor(base, cv2.COLOR_GRAY2BGR)
    canvas[:] = np.clip(canvas.astype(int) * np.array([0.6, 0.85, 1.0]), 0, 255).astype(np.uint8)
    for h, piece in tops.items():
        cx = origin[0] + 1.5 * TILE_R * h.q
        cy = origin[1] + TILE_H * (h.r + h.q / 2)
        pts = np.array(
            [
                [
                    cx + (TILE_R - 3) * math.cos(math.radians(60 * k)),
                    cy + (TILE_R - 3) * math.sin(math.radians(60 * k)),
                ]
                for k in range(6)
            ],
            np.int32,
        )
        cv2.fillPoly(canvas, [pts], (230, 235, 240) if piece.color is Color.WHITE else (0, 0, 0))
        cv2.circle(canvas, (int(cx), int(cy)), 40, _glyph_bgr(piece.kind), -1)  # 種類ごとの絵の色
    return canvas


def _frame(scene: NDArray[np.uint8], window_x: int) -> NDArray[np.uint8]:
    return np.ascontiguousarray(scene[:, window_x : window_x + SCREEN_W])


def _board_spanning_screen() -> dict[HexCoord, Piece]:
    # 幅が画面より広い盤(列の範囲 約 11 列)
    return tops_from(
        state(
            [
                (0, 0, W, Kind.QUEEN),
                (3, -1, B, Kind.ANT),
                (5, -2, W, Kind.GRASSHOPPER),
                (7, -3, B, Kind.QUEEN),
                (-2, 1, B, Kind.BEETLE),
            ],
            turn=10,
        )
    )


def tops_from(s: object) -> dict[HexCoord, Piece]:
    return {a: p for a in s.stacks for p in [s.top(a)] if p is not None}  # type: ignore[attr-defined]


def test_measured_shift_matches_the_pan() -> None:
    tops = _board_spanning_screen()
    origin = (500.0, 1200.0)
    scene = _scene(tops, origin)
    centre = _frame(scene, 300)
    left = _frame(scene, 300 + PAN)  # 内容は左へ PAN ずれる
    dx, dy = measure_shift(centre, left)
    assert abs(dx + PAN) < 3
    assert abs(dy) < 3


def test_stitched_frames_read_the_whole_wide_board() -> None:
    tops = _board_spanning_screen()
    origin = (500.0, 1200.0)
    scene = _scene(tops, origin)
    # 左寄せ・中央・右寄せの3枚。どの画面にも、全部の駒は一度には入らない
    frames = [_frame(scene, 300), _frame(scene, 300 + PAN), _frame(scene, 300 - PAN)]
    # 基準の画面に入らない駒があることを確かめる(継ぎ合わせの必要性)
    single = read_tiles(find_tiles(frames[0]))
    assert len(single.tops) < len(tops)
    merged = read_stitched(frames)
    assert merged.problems == ()
    assert len(merged.tops) == len(tops)
    assert sorted(
        (
            a.q - min(h.q for h in merged.tops),
            a.r - min(h.r for h in merged.tops),
            p.color.name,
            p.kind.value,
        )
        for a, p in merged.tops.items()
    ) == sorted(
        (a.q - min(h.q for h in tops), a.r - min(h.r for h in tops), p.color.name, p.kind.value)
        for a, p in tops.items()
    )
