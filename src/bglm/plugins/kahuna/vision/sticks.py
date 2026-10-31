"""盤上の杖コマの検出。

自分の杖コマは「白い長方形」、相手の杖コマは「黒い長方形」(どちらも茶色の模様の縁つき)。
白/黒の内側の連結成分から、長方形らしいものを拾い、最も近い点線に割り当てる。
"""

from dataclasses import dataclass

import cv2
import numpy as np
from numpy.typing import NDArray

from bglm.core.models import Point
from bglm.plugins.kahuna.logic.models import BoardDef, Player

# 盤(島のある範囲)。左の相手の手札と、右の自分の手札を除く(原寸)
MAP_ROI = (
    740,
    190,
    1700,
    975,
)  # 下端は最も下の点線(y=930)の下。捨て札の白いカードを除く  # x0, y0, x1, y1

WHITE_MIN = 228  # 自分の杖コマの内側: 全チャンネルがこの値以上
BLACK_MAX = 40  # 相手の杖コマの内側: 全チャンネルがこの値以下
AREA_RANGE = (550, 2600)  # 内側の面積(原寸の画素数)
MIN_ASPECT = 1.6  # 長辺/短辺
MIN_FILL = 0.80  # 面積 / 外接する回転長方形の面積
MAX_DISTANCE = 85.0  # 点線の位置から、杖コマの中心までの許容距離


@dataclass(frozen=True)
class StickBlob:
    owner: Player
    center: Point
    area: int


def find_blobs(image: NDArray[np.uint8]) -> list[StickBlob]:
    """画像から、杖コマらしい長方形を、持ち主つきで全部拾う。"""
    x0, y0, x1, y1 = MAP_ROI
    roi = image[y0:y1, x0:x1]
    masks = {
        Player.ME: (roi.min(axis=2) >= WHITE_MIN),
        Player.OPPONENT: (roi.max(axis=2) <= BLACK_MAX),
    }
    blobs: list[StickBlob] = []
    kernel = np.ones((3, 3), np.uint8)
    for owner, mask in masks.items():
        cleaned = cv2.morphologyEx(mask.astype(np.uint8) * 255, cv2.MORPH_OPEN, kernel)
        count, labels, stats, _ = cv2.connectedComponentsWithStats(cleaned)
        for i in range(1, count):
            area = int(stats[i, cv2.CC_STAT_AREA])
            if not AREA_RANGE[0] <= area <= AREA_RANGE[1]:
                continue
            points = np.argwhere(labels == i)[:, ::-1].astype(np.float32)  # (x, y)
            (cx, cy), (w, h), _ = cv2.minAreaRect(points)
            short, long_ = min(w, h), max(w, h)
            if short < 1 or long_ / short < MIN_ASPECT or area / (w * h) < MIN_FILL:
                continue
            blobs.append(StickBlob(owner, Point(int(cx) + x0, int(cy) + y0), area))
    return blobs


def assign_to_lines(
    board: BoardDef, blobs: list[StickBlob]
) -> tuple[list[Player | None], list[StickBlob]]:
    """杖コマを、最も近い点線に割り当てる。

    返り値は (点線ごとの持ち主, 割り当てられなかった杖コマ)。1本の点線に複数が近い場合は、
    近い方を採り、残りは「割り当てられなかった」に入れる。どの点線からも遠い物(選択中の
    カードの白い面など)は、杖コマではないので、割り当てられなかった物に含めない。
    """
    owners: list[Player | None] = [None] * len(board.lines)
    best: list[tuple[float, StickBlob] | None] = [None] * len(board.lines)
    unassigned: list[StickBlob] = []
    for blob in blobs:
        distances = [
            float(np.hypot(blob.center.x - ln.position.x, blob.center.y - ln.position.y))
            for ln in board.lines
        ]
        line = int(np.argmin(distances))
        if distances[line] > MAX_DISTANCE:
            continue
        current = best[line]
        if current is None or distances[line] < current[0]:
            if current is not None:
                unassigned.append(current[1])
            best[line] = (distances[line], blob)
        else:
            unassigned.append(blob)
    for line, entry in enumerate(best):
        if entry is not None:
            owners[line] = entry[1].owner
    return owners, unassigned
