"""場札の名前を全フレームから切り出し、似たものをまとめる(テンプレート作りの下準備、Phase 5)。

出力: datasets/raw/kahuna/work/market_names/cluster_XX.png(代表の名前画像)と sheet.png(個数つきの一覧)。
島名は人が見て付ける(scripts/kahuna/build_templates.py に対応表を書く)。
"""

import sys
from pathlib import Path

import cv2
import numpy as np

SESSION = Path("datasets/raw/kahuna/session1")
OUT = Path("datasets/raw/kahuna/work/market_names")

# 場札3枚の位置(原寸)。名前の文字は、カードの上端から少し下にある
SLOT_X = (1185, 1390, 1600)
SLOT_W = 195
NAME_Y, NAME_H = 1012, 56


def load(path: Path) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None
    return np.asarray(image)


def card_present(slot: np.ndarray) -> bool:
    """カードの白い縁や名前の白い文字が、十分にあるか。"""
    white = np.count_nonzero(slot.min(axis=2) > 205)
    return bool(white > 0.06 * slot.shape[0] * slot.shape[1])


def cluster() -> tuple[list[int], list[np.ndarray], list[list[np.ndarray]]]:
    """(個数順のクラスタの番号, 代表, 各クラスタのメンバー)。"""
    clusters: list[list[np.ndarray]] = []
    reps: list[np.ndarray] = []
    for path in sorted(SESSION.glob("f*.png")):
        frame = load(path)
        for x in SLOT_X:
            slot = frame[NAME_Y : NAME_Y + NAME_H, x + 20 : x + SLOT_W - 20]
            if not card_present(slot):
                continue
            gray = np.asarray(cv2.cvtColor(slot, cv2.COLOR_BGR2GRAY), dtype=np.uint8)
            best, best_score = -1, 0.0
            for i, rep in enumerate(reps):
                score = float(
                    cv2.matchTemplate(gray, rep[8:-8, 12:-12], cv2.TM_CCOEFF_NORMED).max()
                )
                if score > best_score:
                    best, best_score = i, score
            if best >= 0 and best_score > 0.80:
                clusters[best].append(gray)
            else:
                reps.append(gray)
                clusters.append([gray])
    order = sorted(range(len(clusters)), key=lambda i: -len(clusters[i]))
    return order, reps, clusters


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    order, reps, clusters = cluster()
    sheet = []
    for rank, i in enumerate(order):
        rep = cv2.cvtColor(reps[i], cv2.COLOR_GRAY2BGR)
        label = np.full((rep.shape[0], 150, 3), 255, np.uint8)
        text = f"{rank:02d} n={len(clusters[i])}"
        cv2.putText(label, text, (5, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 2)
        sheet.append(np.hstack([label, rep]))
        cv2.imencode(".png", reps[i])[1].tofile(str(OUT / f"cluster_{rank:02d}.png"))
    print(f"クラスタ数: {len(clusters)}  個数: {[len(clusters[i]) for i in order]}")
    cols = 2
    rows = [np.hstack(sheet[r : r + cols]) for r in range(0, len(sheet) - len(sheet) % cols, cols)]
    if rows:
        cv2.imencode(".png", np.vstack(rows))[1].tofile(str(OUT / "sheet.png"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
