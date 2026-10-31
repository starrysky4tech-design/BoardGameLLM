"""全フレームの島の石を、テンプレートで検出して位置をまとめる(Phase 5)。

テンプレートは、自分の石(DUDA)と相手の石(FAAA)を、フレーム126から切り出す(原寸)。
出力: 検出位置のクラスタ(中心と回数、持ち主)と、島ごとの割り当て案。
"""

import sys
from pathlib import Path

import cv2
import numpy as np

SESSION = Path("datasets/raw/kahuna/session1")
TEMPLATES_DIR = Path("assets/kahuna/templates/stones")
SOURCE_FRAME = 126
# 切り出す中心(原寸)。半径33の円の内側に収まる、一辺48の正方形
CENTERS = {"me": (964, 516), "opponent": (1447, 536)}
HALF = 24
MAP_ROI = (740, 190, 1700, 1000)


def load(path: Path) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None
    return np.asarray(image)


def peaks(score: np.ndarray, threshold: float, radius: int = 30) -> list[tuple[int, int, float]]:
    found: list[tuple[int, int, float]] = []
    work = score.copy()
    while True:
        _, best, _, loc = cv2.minMaxLoc(work)
        if best < threshold:
            return found
        x, y = loc
        found.append((x, y, float(best)))
        work[max(0, y - radius) : y + radius, max(0, x - radius) : x + radius] = -1


def main() -> int:
    files = sorted(SESSION.glob("f*.png"))
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    reference = load(files[SOURCE_FRAME])
    templates = {}
    for owner, (cx, cy) in CENTERS.items():
        crop = reference[cy - HALF : cy + HALF, cx - HALF : cx + HALF]
        templates[owner] = crop
        cv2.imencode(".png", crop)[1].tofile(str(TEMPLATES_DIR / f"{owner}.png"))

    x0, y0, x1, y1 = MAP_ROI
    detections: dict[str, list[tuple[int, int, float]]] = {"me": [], "opponent": []}
    for path in files:
        roi = load(path)[y0:y1, x0:x1]
        for owner, template in templates.items():
            score = cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED)
            for x, y, s in peaks(score, 0.72):
                detections[owner].append((x + HALF + x0, y + HALF + y0, s))

    for owner, items in detections.items():
        clusters: list[list[tuple[int, int, float]]] = []
        for item in items:
            for cluster in clusters:
                mean_x = float(np.mean([c[0] for c in cluster]))
                mean_y = float(np.mean([c[1] for c in cluster]))
                if np.hypot(item[0] - mean_x, item[1] - mean_y) < 25:
                    cluster.append(item)
                    break
            else:
                clusters.append([item])
        clusters.sort(key=lambda c: -len(c))
        print(f"--- {owner}: 検出{len(items)}件、{len(clusters)}か所")
        for c in clusters:
            cx, cy = int(np.median([p[0] for p in c])), int(np.median([p[1] for p in c]))
            print(f"  ({cx:4d},{cy:4d}) {len(c):3d}回 スコア平均 {np.mean([p[2] for p in c]):.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
