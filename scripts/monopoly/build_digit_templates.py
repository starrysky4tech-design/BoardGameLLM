"""所持金の数字テンプレートを、局 A のラベル付き画像から切り出す。

ラベル(labels.json)は手で付けた値。桁数がラベルと一致する読み取りだけを、桁ごとに登録する。
使い方: uv run python scripts/monopoly/build_digit_templates.py
"""

import json
from pathlib import Path

import cv2
import numpy as np

from bglm.plugins.monopoly.vision.cash import AI_X, SELF_X, YEN_DIR, extract_glyphs

ROOT = Path("datasets/eval/monopoly/cash")
OUT = Path("src/bglm/plugins/monopoly/data/digits")
SOURCES = (
    "A/",
    "C/",
    "D/",
    "F/",
    "J/",
)  # 切り出しに使う局。局 B は評価専用。局 D は目視確認済みの画像のみ(ラベル status ok)
SAME_PIXELS = 12  # これ以下の差の形は、同じ見え方として 1 つにまとめる


def main() -> None:
    labels = json.loads((ROOT / "labels.json").read_text(encoding="utf-8"))
    for old in [*OUT.glob("*.png"), *YEN_DIR.glob("*.png")]:
        old.unlink()
    yens: list[np.ndarray] = []
    store: dict[str, list[np.ndarray]] = {}
    skipped = 0
    seen_refs: set[int] = set()
    for key, info in sorted(labels.items()):
        if not key.startswith(SOURCES) or info["status"] != "ok":
            continue
        ref = info["ref"] or key  # 局 C は同じ画面を数枚撮るため、重複はグリフの比較で除く
        if ref in seen_refs:
            continue
        seen_refs.add(ref)
        raw = cv2.imread(str(ROOT / key))
        if raw is None:
            raise FileNotFoundError(key)
        image = np.asarray(raw, dtype=np.uint8)
        for side, x_range in (("self", SELF_X), ("ai", AI_X)):
            value = info[side]
            if value is None:
                continue
            glyphs = extract_glyphs(image, x_range, verify_yen=False)
            text = str(abs(value))
            if glyphs is None or len(glyphs.digits) != len(text) or glyphs.negative != (value < 0):
                skipped += 1
                print("skip", key, side, value)
                continue
            if all(int(np.count_nonzero(v != glyphs.yen)) > SAME_PIXELS for v in yens):
                yens.append(glyphs.yen)
            for char, glyph in zip(text, glyphs.digits, strict=True):
                variants = store.setdefault(char, [])
                if all(int(np.count_nonzero(v != glyph)) > SAME_PIXELS for v in variants):
                    variants.append(glyph)
    OUT.mkdir(parents=True, exist_ok=True)
    YEN_DIR.mkdir(parents=True, exist_ok=True)
    for n, yen in enumerate(yens):
        cv2.imwrite(str(YEN_DIR / f"Y_{n}.png"), yen)
    for char, variants in sorted(store.items()):
        for n, glyph in enumerate(variants):
            cv2.imwrite(str(OUT / f"{char}_{n}.png"), glyph)
    print({c: len(v) for c, v in sorted(store.items())}, "yen", len(yens), "skipped", skipped)


if __name__ == "__main__":
    main()
