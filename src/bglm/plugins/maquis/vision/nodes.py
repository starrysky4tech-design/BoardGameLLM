"""地点と任務の枠の読み取り: 団員・巡回がいるか、赤い「!」(帰還不可)が付いているか、監獄に団員がいるか。

方式(実機の画面で確かめた):
- 在・不在: 地点の中心の小さな領域を、空き地の基準画像(data/templates/nodes/)と照合する。画面は決まった絵なので、
  空き地は相関 1.00 で一致し、写真が出ると 0.6 未満になる(測定: 18 地点 × 6 フレームで取り違え無し)。
- 巡回か団員か: 巡回(ミリス隊員)の写真は紺色、団員の写真は茶・緑・灰色。紺色の画素の割合で分ける。
- 「!」: 赤い円の連結成分(面積 800 以上)を、地点の中心から右下の決まった位置で割り当てる。
任務の枠は、画面上部の2枚。団員の写真の枠(黒い縁)で在・不在を判定する。
"""

from dataclasses import dataclass
from enum import Enum
from functools import cache
from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray

from bglm.plugins.maquis.vision import layout
from bglm.toolkit.components import connected_components
from bglm.toolkit.images import gray, load_image

NODE_DIR = Path(__file__).resolve().parent.parent / "data" / "templates" / "nodes"
EMPTY_MIN = 0.90  # 基準との相関がこれ以上なら空き地
OCCUPIED_MAX = 0.70  # これ未満なら写真が出ている。間は読めない
BLUE_PATROL_MIN = 0.12  # 紺色の画素の割合(測定: 巡回 0.24〜0.37、団員 0.00)
BLUE_AGENT_MAX = 0.05
BLUE_HALF = 45
BANG_AREA_MIN = 800
BANG_SIZE = (50, 64)  # 「!」の円の幅・高さの範囲(実測 57〜58)
MAP_LEFT = 640  # 左の資材の列より右だけが地図
MISSION_BANG_RADIUS = 30
PHOTO_BORDER_MIN = 0.6  # 任務の枠の写真の枠線(黒)の割合(測定: あり 0.82、なし 0.03〜0.17)
PHOTO_BORDER_DARK = 45
PHOTO_BORDER_THICK = 4


class Occupant(Enum):
    EMPTY = "empty"
    AGENT = "agent"
    PATROL = "patrol"


@dataclass(frozen=True)
class NodeReading:
    occupant: Occupant | None  # 読めなければ None
    score: float  # 基準との相関(低いほど写真が出ている)
    problem: str | None = None


@cache
def _references() -> dict[str, list[NDArray[np.uint8]]]:
    """地点ごとの空き地の基準画像。`<地点>.png` と `<地点>__<n>.png`(同じ地点の別の見え方。カフェ)。"""
    refs: dict[str, list[NDArray[np.uint8]]] = {}
    for path in sorted(NODE_DIR.glob("*.png")):
        image = load_image(path, cv2.IMREAD_GRAYSCALE)
        if image is not None:
            refs.setdefault(path.stem.split("__")[0], []).append(image)
    return refs


def read_node(image: NDArray[np.uint8], node: str) -> NodeReading:
    """地点の在・不在と、巡回か団員か。"""
    if node == "cafe":
        # カフェの飾りの写真(勧誘できる人)は対局ごとに顔が違い、勧誘で減るので、基準画像は使えない。
        # 団員の写真の枠があれば団員、無ければ空き。巡回は来ない地点
        return NodeReading(Occupant.AGENT if _cafe_photo(image) else Occupant.EMPTY, 1.0)
    refs = _references()
    if node not in refs:
        return NodeReading(None, 0.0, f"no_reference:{node}")
    cx, cy = layout.NODE_CENTER[node]
    half = layout.NODE_REF_HALF
    patch = gray(image)[cy - half : cy + half, cx - half : cx + half]
    score = max(float(cv2.matchTemplate(patch, r, cv2.TM_CCOEFF_NORMED)[0, 0]) for r in refs[node])
    if score >= EMPTY_MIN:
        return NodeReading(Occupant.EMPTY, score)
    if score >= OCCUPIED_MAX:
        return NodeReading(None, score, f"ambiguous:{node}")
    blue = _blue_fraction(image, (cx, cy))
    if blue >= BLUE_PATROL_MIN:
        return NodeReading(Occupant.PATROL, score)
    if blue <= BLUE_AGENT_MAX:
        return NodeReading(Occupant.AGENT, score)
    return NodeReading(None, score, f"ambiguous_color:{node}")


def _cafe_photo(image: NDArray[np.uint8]) -> bool:
    """カフェに団員の写真の枠があるか(上端の黒い横線。飾りの写真の枠はもっと低い位置)。"""
    y0, y1 = layout.CAFE_PHOTO_TOP
    x0, x1 = layout.CAFE_PHOTO_X
    strip = gray(image)[y0:y1, x0:x1]
    # 枠線は3px(4行の帯のうち3行)。団員がいれば 0.75、飾りだけなら 0.0
    return float(np.mean(strip < PHOTO_BORDER_DARK)) >= 0.6


def _blue_fraction(image: NDArray[np.uint8], centre: tuple[int, int]) -> float:
    x, y = centre
    patch = image[y - BLUE_HALF : y + BLUE_HALF, x - BLUE_HALF : x + BLUE_HALF].astype(np.int16)
    blue, red = patch[..., 0], patch[..., 2]
    return float(np.mean((blue > red + 35) & (blue > 70)))


def read_bangs(image: NDArray[np.uint8]) -> list[tuple[float, float]]:
    """赤い「!」の円の中心。地図(x ≥ 640)と上部バーの両方。"""
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    red = (((hue < 8) | (hue > 172)) & (sat > 170) & (val > 80) & (val < 200)).astype(np.uint8)
    components, _ = connected_components(red)
    out: list[tuple[float, float]] = []
    for c in components:
        if c.area < BANG_AREA_MIN or c.cx < MAP_LEFT:
            continue
        if not (
            BANG_SIZE[0] <= c.width <= BANG_SIZE[1] and BANG_SIZE[0] <= c.height <= BANG_SIZE[1]
        ):
            continue
        out.append((c.cx, c.cy))
    return out


def stranded_nodes(bangs: list[tuple[float, float]]) -> frozenset[str]:
    """地点のうち、「!」が付いているもの。各「!」を、中心から右下の位置が最も近い地点に割り当てる。"""
    found: set[str] = set()
    ox, oy = layout.BANG_OFFSET
    for bx, by in bangs:
        if by < 140:  # 上部バー(任務の枠)
            continue
        node = min(
            layout.NODE_CENTER,
            key=lambda n: (
                (layout.NODE_CENTER[n][0] + ox - bx) ** 2
                + (layout.NODE_CENTER[n][1] + oy - by) ** 2
            ),
        )
        cx, cy = layout.NODE_CENTER[node]
        if (
            abs(cx + ox - bx) <= layout.BANG_TOLERANCE
            and abs(cy + oy - by) <= layout.BANG_TOLERANCE
        ):
            found.add(node)
    return frozenset(found)


def mission_bangs(bangs: list[tuple[float, float]]) -> frozenset[str]:
    """任務の枠のうち、「!」が付いているもの。"""
    found: set[str] = set()
    for bx, by in bangs:
        for slot, (mx, my) in layout.MISSION_BANG.items():
            if (bx - mx) ** 2 + (by - my) ** 2 <= MISSION_BANG_RADIUS**2:
                found.add(slot)
    return frozenset(found)


def mission_has_agent(image: NDArray[np.uint8], slot: str) -> tuple[bool, float]:
    """任務の枠に団員の写真が出ているか。写真の枠線(黒い縁)の割合と、その値。"""
    left = layout.MISSION_LEFT[slot]
    x0, x1 = left + layout.MISSION_PHOTO_X[0], left + layout.MISSION_PHOTO_X[1]
    y0, y1 = layout.MISSION_PHOTO_Y
    g = gray(image)
    t = PHOTO_BORDER_THICK
    strips = [
        g[y0 : y0 + t, x0:x1],
        g[y1 - t : y1, x0:x1],
        g[y0:y1, x0 : x0 + t],
        g[y0:y1, x1 - t : x1],
    ]
    fraction = float(np.mean([np.mean(s < PHOTO_BORDER_DARK) for s in strips]))
    return fraction >= PHOTO_BORDER_MIN, fraction
