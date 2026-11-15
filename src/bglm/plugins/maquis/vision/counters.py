"""数と状態の読み取り: 資材(丸の塗り)、団員の数(N/M)、フェイズのアイコン、任務の★。

実機の画面で確かめた値:
- 資材の丸の中心の明るさは、塗り 164 以上・空 71 以下(しきい値 115)
- フェイズのアイコン: 自転車(配置)は黄緑、旗(行動)は橙。赤と緑の差で分ける
- ★は下から点灯する。点灯は金(BGR 87,175,207)、消灯は淡いクリーム(200,236,246)
"""

from dataclasses import dataclass
from enum import Enum
from functools import cache
from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray

from bglm.plugins.maquis.logic.models import Resources
from bglm.plugins.maquis.vision import layout
from bglm.plugins.maquis.vision.digits import read_agent_counts
from bglm.toolkit.images import crop, gray, load_image

MISSION_ART_DIR = Path(__file__).resolve().parent.parent / "data" / "templates" / "missions"
MISSION_ART_TOL = 12  # 絵の帯の画素の差(0〜255)がこれ未満なら一致とみなす
MISSION_ART_MIN = 0.9  # 一致する画素の割合の下限

CIRCLE_PATCH = 2  # 丸の中心から±の画素数(平均を取る)
PHASE_RING = 38  # アイコンの円(中心から±)。縁の色の割合で分ける(測定: 旗 橙 0.44、自転車 黄緑 0.18)
PHASE_FRACTION_MIN = 0.08
STAR_PATCH = 6


class PhaseIcon(Enum):
    BICYCLE = "bicycle"  # 配置フェイズ
    FLAG = "flag"  # 行動フェイズ


@dataclass(frozen=True)
class ResourcesReading:
    resources: Resources | None
    problems: tuple[str, ...] = ()


def _filled(image: NDArray[np.uint8], x: int, y: int) -> bool:
    p = CIRCLE_PATCH
    return float(image[y - p : y + p + 1, x - p : x + p + 1].mean()) >= layout.CIRCLE_FILLED_MIN


def _count_row(image: NDArray[np.uint8], y: int, columns: int) -> tuple[int, bool]:
    """1行の塗りの数と、塗りが左から連続しているか。"""
    flags = [_filled(image, x, y) for x in layout.RESOURCE_COLS[:columns]]
    count = sum(flags)
    return count, flags == [True] * count + [False] * (columns - count)


def read_resources(image: NDArray[np.uint8]) -> ResourcesReading:
    """資材の数。丸が左から連続して塗られていなければ(読み誤りか、演出の途中)問題とする。"""
    values: dict[str, int] = {}
    problems: list[str] = []
    for name, rows in layout.RESOURCE_ROWS.items():
        total = 0
        for row_y, columns in zip(
            rows, layout.MORALE_ROW_COUNTS if name == "morale" else (4,), strict=False
        ):
            count, contiguous = _count_row(image, row_y, columns)
            total += count
            if not contiguous:
                problems.append(f"resource_gap:{name}")
        values[name] = total
    if problems:
        return ResourcesReading(None, tuple(problems))
    return ResourcesReading(Resources(**values))


def read_agent_numbers(image: NDArray[np.uint8]) -> tuple[tuple[int, int] | None, float]:
    """「未配置 / 使える団員」。読めなければ None。"""
    return read_agent_counts(crop(image, layout.AGENTS_BOX))


def read_phase(image: NDArray[np.uint8]) -> tuple[PhaseIcon | None, float]:
    """フェイズのアイコン(配置 = 自転車、行動 = 旗)。確信度は、しきい値からの離れ(0〜1)。"""
    x0, y0, x1, y1 = layout.PHASE_BOX
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    ring = image[cy - PHASE_RING : cy + PHASE_RING, cx - PHASE_RING : cx + PHASE_RING].reshape(
        -1, 3
    )
    b, g, r = (ring[:, i].astype(int) for i in range(3))
    orange = float(np.mean((r > 200) & (g > 120) & (g < 200) & (b < 140)))
    green = float(np.mean((g > 170) & (r > 150) & (b < 150) & (np.abs(r - g) < 25)))
    if orange >= PHASE_FRACTION_MIN and green < 0.05:
        return PhaseIcon.FLAG, min(1.0, orange / 0.4)
    if green >= PHASE_FRACTION_MIN and orange < 0.05:
        return PhaseIcon.BICYCLE, min(1.0, green / 0.16)
    return None, 0.0


@cache
def _mission_arts() -> dict[str, NDArray[np.uint8]]:
    arts: dict[str, NDArray[np.uint8]] = {}
    for path in sorted(MISSION_ART_DIR.glob("*.png")):
        image = load_image(path, cv2.IMREAD_GRAYSCALE)
        if image is not None:
            arts[path.stem] = image
    return arts


def mission_kind(image: NDArray[np.uint8], slot: str) -> tuple[str | None, float]:
    """任務の枠の絵から、任務の種類(`spy_support`、`factory_sabotage`)。見たことの無い任務は None。

    ★の位置と箱の数は任務ごとに違うので、種類が分かるものだけを読む(実機で確かめたのはこの2つ)。
    """
    left = layout.MISSION_LEFT[slot]
    x0, x1 = left + layout.MISSION_ART_X[0], left + layout.MISSION_ART_X[1]
    y0, y1 = layout.MISSION_ART_Y
    strip = gray(image)[y0:y1, x0:x1]
    best: tuple[str | None, float] = (None, 0.0)
    for name, ref in _mission_arts().items():
        score = float(np.mean(np.abs(strip.astype(int) - ref.astype(int)) < MISSION_ART_TOL))
        if score > best[1]:
            best = (name, score)
    return best if best[1] >= MISSION_ART_MIN else (None, best[1])


def read_stars(image: NDArray[np.uint8], slot: str) -> tuple[int, bool]:
    """任務の点灯した★の数と、下から連続して点灯しているか(実機: 下から点灯する)。"""
    lit_color = np.array(layout.STAR_LIT_BGR, dtype=float)
    off_color = np.array(layout.STAR_OFF_BGR, dtype=float)
    flags: list[bool] = []
    for x, y in layout.MISSION_STARS[slot]:
        patch = image[y - STAR_PATCH : y + STAR_PATCH + 1, x - STAR_PATCH : x + STAR_PATCH + 1]
        mean = patch.reshape(-1, 3).mean(axis=0)
        flags.append(bool(np.linalg.norm(mean - lit_color) < np.linalg.norm(mean - off_color)))
    count = sum(flags)
    # 上から並べた順。下の count 個だけが点灯しているはず
    ordered = [False] * (len(flags) - count) + [True] * count
    return count, flags == ordered
