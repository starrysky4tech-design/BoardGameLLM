"""Maquis の認識に使うテンプレートを、記録した実画面(datasets/raw/maquis/feasibility/)から作る。

出力: src/bglm/plugins/maquis/data/templates/{nodes,digits,screens,icons}/。
元の画面は Git 管理外。ここで作る小さな切り出しだけを、プラグインのデータとして管理する(Monopoly の data/digits と同じ扱い)。
実行: uv run python -m scripts.maquis.build_templates
"""

from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray

from bglm.plugins.maquis.vision import layout
from bglm.plugins.maquis.vision.digits import glyph_mask, normalize_glyph, split_glyphs
from bglm.toolkit.images import crop, gray, load_image

RAW = Path("datasets/raw/maquis/feasibility")
OUT = Path("src/bglm/plugins/maquis/data/templates")

# 空き地の基準: 対局の開始直後(団員も巡回も出ていない)のフレーム。隠れ家は団員の写真が常に出るので除く
EMPTY_BOARD = "game_001"
# 「N/M」の数字: (フレーム, 表示の文字列)。実機の画面を見て決めた
AGENT_COUNTS: tuple[tuple[str, str], ...] = (
    ("game_001", "3/3"),
    ("y_p1", "2/3"),
    ("y_p2", "1/3"),
    ("y_p3", "0/3"),
    ("y_end", "4/4"),
    ("z_p1", "3/4"),
    ("z_p2", "2/4"),
    ("z_p3b", "1/4"),
    ("z_p4b", "0/4"),
    ("w_p5", "0/5"),  # 2026-11-15 の通し。描画のずれ(-72px)を補正して保存した画面
)
# 山札の画面のカード: (フレーム, 枠の左端 x, 3つの絵の地点)。絵と名前を目で見て決め、絵の一致でも検証した
DECK_CARDS: tuple[tuple[str, int, tuple[str, str, str]], ...] = (
    ("g_deck_00", 582, ("radio_a", "parade_street", "grocer")),
    ("g_deck_01", 912, ("pont_leveque", "black_market", "doctor")),
    ("g_deck_02", 798, ("grocer", "pont_du_nord", "black_market_fence")),
    ("g_deck_03", 697, ("radio_a", "pont_leveque", "black_market")),
    ("g_deck_04", 588, ("radio_b", "grocer", "black_market")),
    ("g_deck_05", 933, ("pont_leveque", "pont_du_nord", "doctor")),
    ("g_deck_06", 822, ("black_market_fence", "pont_du_nord", "pont_leveque")),
    ("g_deck_07", 749, ("radio_b", "parade_street", "pont_leveque")),
    ("u_deck2", 582, ("grocer", "slums", "doctor")),  # 山札の先頭(混ぜ直した後)
    ("u_deck2", 1261, ("radio_b", "grocer", "black_market")),  # 捨札の先頭
)
DEFEAT_FRAME = "x_t1_end2"  # 「レジスタンス壊滅」
TITLE_FRAME = "m_menu"  # メインメニュー
ICON_WINDOW = (120, 85)  # 絵の探索窓(幅, 高さ)。テンプレートは中央を切り出す
ICON_MARGIN = (14, 12)


def load(name: str) -> NDArray[np.uint8]:
    image = load_image(RAW / f"{name}.png")
    if image is None:
        raise SystemExit(f"素材が無い: {RAW / name}.png")
    return image


def save(path: Path, image: NDArray[np.uint8]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), image):
        raise SystemExit(f"書けない: {path}")


def build_nodes() -> None:
    image = gray(load(EMPTY_BOARD))
    half = layout.NODE_REF_HALF
    for node, (x, y) in layout.NODE_CENTER.items():
        if node == "hideout":
            continue
        if node == "cafe":
            continue  # 飾りの写真が対局ごとに違う。団員の写真の枠で判定する(nodes.py)
        save(OUT / "nodes" / f"{node}.png", image[y - half : y + half, x - half : x + half])


def build_missions() -> None:
    """任務の枠の絵の上端の帯。対局の開始直後(game_001)の、スパイ支援(任務A)と工場破壊(任務B)。"""
    image = gray(load(EMPTY_BOARD))
    y0, y1 = layout.MISSION_ART_Y
    for slot, kind in (("mission_a", "spy_support"), ("mission_b", "factory_sabotage")):
        left = layout.MISSION_LEFT[slot]
        x0, x1 = left + layout.MISSION_ART_X[0], left + layout.MISSION_ART_X[1]
        save(OUT / "missions" / f"{kind}.png", image[y0:y1, x0:x1])


def build_digits() -> None:
    samples: dict[str, list[NDArray[np.uint8]]] = {}
    for name, text in AGENT_COUNTS:
        glyphs = split_glyphs(glyph_mask(crop(load(name), layout.AGENTS_BOX)))
        if len(glyphs) != 3:
            raise SystemExit(f"{name}: 文字が3つに分かれない({len(glyphs)})")
        for glyph, char in zip(glyphs, text, strict=True):
            samples.setdefault("slash" if char == "/" else char, []).append(normalize_glyph(glyph))
    for key, items in samples.items():
        # 同じ文字の複数の例は、平均して2値化する
        mean = np.mean(np.stack(items), axis=0)
        save(OUT / "digits" / f"{key}.png", np.where(mean >= 127, 255, 0).astype(np.uint8))


def half(image: NDArray[np.uint8]) -> NDArray[np.uint8]:
    """半分の大きさのグレースケール(画面の判別は、同じ大きさに縮めて照合する)。"""
    return np.asarray(cv2.resize(gray(image), None, fx=0.5, fy=0.5), dtype=np.uint8)


def build_screens() -> None:
    save(OUT / "screens" / "end_defeat.png", half(crop(load(DEFEAT_FRAME), layout.END_TITLE_BOX)))
    save(OUT / "screens" / "title_menu.png", half(crop(load(TITLE_FRAME), (429, 391, 933, 960))))
    # 「ターンを終了しますか?」
    save(OUT / "screens" / "confirm_dialog.png", half(crop(load("r_t3"), layout.CONFIRM_BOX)))
    # 「巡回カード」の見出し
    save(OUT / "screens" / "deck_title.png", half(crop(load("g_deck_00"), layout.END_TITLE_BOX)))


def build_icons() -> None:
    counts: dict[str, int] = {}
    w, h = ICON_WINDOW
    mx, my = ICON_MARGIN
    for name, left, places in DECK_CARDS:
        image = gray(load(name))
        for slot, place in enumerate(places):
            y0, y1 = layout.CARD_ICON_Y[slot]
            x0 = left + layout.CARD_ICON_X[0]
            window = image[y0 : y0 + h, x0 : x0 + w]
            n = counts.get(place, 0)
            counts[place] = n + 1
            save(OUT / "icons" / f"{place}__{n}.png", window[my:-my, mx:-mx])
    print("icons:", counts)


def main() -> None:
    build_nodes()
    build_missions()
    build_digits()
    build_screens()
    build_icons()
    print("done:", OUT)


if __name__ == "__main__":
    main()
