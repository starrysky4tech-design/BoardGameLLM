"""山札・ラウンド・得点の数字を全フレームから切り出し、形でまとめる(テンプレート作りの下準備)。

出力: datasets/raw/kahuna/work/digits/<文脈>_sheet.png(代表の数字と個数)。数字の名前は人が見て付ける。
"""

import sys
from pathlib import Path

import cv2
import numpy as np

SESSION = Path("datasets/raw/kahuna/session1")
OUT = Path("datasets/raw/kahuna/work/digits")

# 文脈ごとの領域(原寸、x0, y0, x1, y1)。座標は目盛り付きの拡大画像で確認した
CONTEXTS = {
    "deck": ((1040, 1006, 1088, 1054), "deck"),  # 赤い丸(中心 1064,1030)の中
    "round": ((1378, 60, 1434, 125), "white"),
    "score_left": ((255, 95, 345, 142), "white"),
    "score_right": ((2060, 95, 2132, 142), "white"),
}
GLYPH_SIZE = (24, 36)  # 幅, 高さ


def load(path: Path) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None
    return np.asarray(image)


def white_mask(roi: np.ndarray, mode: str) -> np.ndarray:
    """白い文字の画素。山札の数字は、赤い丸の内側に限る。"""
    bright = (roi.min(axis=2) > 215).astype(np.uint8) * 255
    if mode == "deck":
        circle = np.zeros(bright.shape, np.uint8)
        cv2.circle(circle, (bright.shape[1] // 2, bright.shape[0] // 2), 22, 255, -1)
        bright = np.asarray(cv2.bitwise_and(bright, circle), dtype=np.uint8)
    return bright


def glyphs(mask: np.ndarray) -> list[tuple[int, np.ndarray]]:
    """連結成分ごとの (左端x, 正規化した形)。小さすぎるものは捨てる。"""
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    found = []
    for i in range(1, count):
        x, y, w, h, area = stats[i]
        if h < 16 or area < 50:
            continue
        crop = (labels[y : y + h, x : x + w] == i).astype(np.uint8) * 255
        found.append((int(x), cv2.resize(crop, GLYPH_SIZE, interpolation=cv2.INTER_AREA)))
    return sorted(found, key=lambda g: g[0])


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, ((x0, y0, x1, y1), mode) in CONTEXTS.items():
        reps: list[np.ndarray] = []
        members: list[int] = []
        for path in sorted(SESSION.glob("f*.png")):
            roi = load(path)[y0:y1, x0:x1]
            for _, glyph in glyphs(white_mask(roi, mode)):
                best, best_score = -1, 0.0
                for i, rep in enumerate(reps):
                    score = float(cv2.matchTemplate(glyph, rep, cv2.TM_CCOEFF_NORMED).max())
                    if score > best_score:
                        best, best_score = i, score
                if best >= 0 and best_score > 0.86:
                    members[best] += 1
                else:
                    reps.append(glyph)
                    members.append(1)
        order = sorted(range(len(reps)), key=lambda i: -members[i])
        tiles = []
        for rank, i in enumerate(order):
            tile = np.full((GLYPH_SIZE[1] + 24, GLYPH_SIZE[0] + 40, 3), 255, np.uint8)
            tile[: GLYPH_SIZE[1], 20 : 20 + GLYPH_SIZE[0]] = cv2.cvtColor(
                255 - reps[i], cv2.COLOR_GRAY2BGR
            )
            cv2.putText(
                tile,
                f"{rank}:{members[i]}",
                (2, GLYPH_SIZE[1] + 16),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (0, 0, 255),
                1,
            )
            tiles.append(tile)
        per_row = 12
        while len(tiles) % per_row:
            tiles.append(np.full_like(tiles[0], 255))
        sheet = np.vstack(
            [np.hstack(tiles[r : r + per_row]) for r in range(0, len(tiles), per_row)]
        )
        sheet = np.asarray(
            cv2.resize(sheet, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST), dtype=np.uint8
        )
        cv2.imencode(".png", sheet)[1].tofile(str(OUT / f"{name}_sheet.png"))
        print(f"{name}: {len(reps)}種類 個数={[members[i] for i in order]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
