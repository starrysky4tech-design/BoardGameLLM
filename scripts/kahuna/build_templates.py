"""記録した画像から、認識のテンプレートを作る(Phase 5)。

出力(Git管理外): assets/kahuna/templates/{names,digits,stones,dialogs}/
  names/<島名>.png   場札の名前(グレースケール、全フレームの平均)
  digits/<文脈>/<数字>_<番号>.png   山札(deck)、得点(score)、ラウンド(round)の数字の形
  dialogs/<名前>.png   決算ダイアログのボタンの文字と、勝者の表示(グレースケール)

名前と数字の対応は、クラスタの代表を人が見て決めた(下の表)。クラスタの順番は個数順で、
同じ記録からなら再現する。記録を変えたら、先に cluster_market_names.py と
cluster_digits.py の出力を見て、対応を確かめ直すこと。
"""

import sys
from pathlib import Path

import cv2
import numpy as np

from bglm.plugins.kahuna.vision.glyphs import extract_glyphs, white_mask
from scripts.kahuna.cluster_market_names import cluster as cluster_names

SESSION = Path("datasets/raw/kahuna/session1")
OUT = Path("assets/kahuna/templates")

# 場札の名前: クラスタの順番(個数順) → 島名
NAME_BY_RANK = {
    0: "ALOA", 1: "KAHU", 2: "HUNA", 3: "LALE", 4: "FAAA", 5: "JOJO",
    6: "BARI", 7: "GOLA", 8: "COCO", 9: "DUDA", 10: "IFFI", 15: "ELAI",
}  # fmt: skip

# 山札の数字: クラスタの順番 → 数字(1は形が2通りある)
DECK_DIGIT_BY_RANK = {
    0: "1", 1: "2", 2: "6", 3: "1", 4: "7", 5: "4", 6: "5", 7: "3", 8: "0", 9: "9", 10: "8",
}  # fmt: skip
SCORE_DIGIT_BY_RANK = {0: "0", 1: "2", 2: "1", 3: "3"}

# ラウンドの数字: フレーム番号の範囲(記録した1ゲームの流れから)
ROUND_FRAMES = {"1": range(10, 60), "2": range(67, 108), "3": range(115, 165)}

# 領域(原寸)。座標は目盛り付きの拡大画像で確認した
DECK_ROI = (1040, 1006, 1088, 1054)
ROUND_ROI = (1378, 60, 1434, 125)
SCORE_RIGHT_ROI = (2060, 95, 2132, 142)


def load(path: Path) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None
    return np.asarray(image)


def save(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imencode(".png", image)[1].tofile(str(path))


def build_names() -> None:
    order, _, clusters = cluster_names()
    for rank, name in NAME_BY_RANK.items():
        members = clusters[order[rank]]
        mean = np.mean(np.stack(members).astype(np.float32), axis=0).astype(np.uint8)
        save(OUT / "names" / f"{name}.png", mean)
        print(f"names/{name}: {len(members)}枚の平均")


def clustered_glyphs(roi: tuple[int, int, int, int], circle: bool) -> list[list[np.ndarray]]:
    """ROI の文字を、形でまとめる(個数順)。画面全体が白いフレームは除く。"""
    x0, y0, x1, y1 = roi
    reps: list[np.ndarray] = []
    members: list[list[np.ndarray]] = []
    for path in sorted(SESSION.glob("f*.png")):
        patch = load(path)[y0:y1, x0:x1]
        mask = white_mask(patch, circle)
        if mask.mean() > 90:  # 全体が白っぽい(ステージ選択など)
            continue
        for _, _, glyph in extract_glyphs(mask):
            best, best_score = -1, 0.0
            for i, rep in enumerate(reps):
                score = float(cv2.matchTemplate(glyph, rep, cv2.TM_CCOEFF_NORMED).max())
                if score > best_score:
                    best, best_score = i, score
            if best >= 0 and best_score > 0.86:
                members[best].append(glyph)
            else:
                reps.append(glyph)
                members.append([glyph])
    order = sorted(range(len(reps)), key=lambda i: -len(members[i]))
    return [members[i] for i in order]


def build_digits() -> None:
    for context, roi, circle, mapping in (
        ("deck", DECK_ROI, True, DECK_DIGIT_BY_RANK),
        ("score", SCORE_RIGHT_ROI, False, SCORE_DIGIT_BY_RANK),
    ):
        groups = clustered_glyphs(roi, circle)
        counts: dict[str, int] = {}
        for rank, digit in mapping.items():
            k = counts.get(digit, 0)
            counts[digit] = k + 1
            mean = np.mean(np.stack(groups[rank]).astype(np.float32), axis=0)
            save(OUT / "digits" / context / f"{digit}_{k}.png", (mean > 127).astype(np.uint8) * 255)
        print(f"digits/{context}: {sorted(counts)}")

    files = sorted(SESSION.glob("f*.png"))
    x0, y0, x1, y1 = ROUND_ROI
    for digit, frames in ROUND_FRAMES.items():
        glyphs = []
        for i in frames:
            found = extract_glyphs(white_mask(load(files[i])[y0:y1, x0:x1]))
            if len(found) == 1:
                glyphs.append(found[0][2])
        mean = np.mean(np.stack(glyphs).astype(np.float32), axis=0)
        save(OUT / "digits" / "round" / f"{digit}_0.png", (mean > 127).astype(np.uint8) * 255)
        print(f"digits/round/{digit}: {len(glyphs)}枚")


# ダイアログの切り出し(フレーム番号, 領域)。座標は目盛り付きの拡大画像で確認した
DIALOG_CROPS = {
    "continue": (63, (1128, 818, 1388, 878)),  # 決算「END OF ROUND n」のボタン
    "next": (170, (1190, 826, 1320, 880)),  # ゲーム終了「END OF GAME」のボタン
    "winner_me": (170, (1040, 655, 1480, 715)),  # 勝者が自分(アカウント名)
    "winner_draw": (63, (1090, 690, 1420, 750)),  # 引き分け
}


def build_dialogs() -> None:
    files = sorted(SESSION.glob("f*.png"))
    for name, (frame, (x0, y0, x1, y1)) in DIALOG_CROPS.items():
        gray = cv2.cvtColor(load(files[frame])[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
        save(OUT / "dialogs" / f"{name}.png", gray)
        print(f"dialogs/{name}: フレーム{frame}")


def build_anchor() -> None:
    """位置合わせの基準: 録画の座標で「FISHERMAN」の名前を切り出す(alignment.ANCHOR_BOX と揃える)。"""
    from bglm.plugins.kahuna.vision.alignment import ANCHOR_BOX

    x0, y0, x1, y1 = ANCHOR_BOX
    frame = load(SESSION / "f0018_220344.png")  # 自分の手番。左上の名前は枚数などで変わらない
    gray = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    save(OUT / "anchor" / "fisherman.png", gray)
    print("anchor/fisherman")


def main() -> int:
    build_names()
    build_digits()
    build_dialogs()
    build_anchor()
    return 0


if __name__ == "__main__":
    sys.exit(main())
