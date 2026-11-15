"""保存画面から、右端の数(キューブ、餌)の桁のテンプレートを集める。

使い方: uv run python -m scripts.wingspan.build_digit_templates [--dry-run]
全体ボードの画面から、右端の 6 つの数を既定の OCR で読み、信頼度の高い読み(0.9 以上)だけを正解とみなして、
桁の切り出しとラベルを対応づける。桁ごとの中央値を `data/templates/digits/` に保存する。
OCR が誤読する桁(「4」を「L」と読む)は、正解が集まらない。その桁は、画像を目で見て ``--label 画像名:行:数`` で足す。
"""

import argparse
import collections
import json
from pathlib import Path

import cv2
import numpy as np

from bglm.plugins.wingspan.vision import layout
from bglm.plugins.wingspan.vision.digits import GLYPH_SIZE, TEMPLATE_DIR, segment_glyphs
from bglm.plugins.wingspan.vision.screens import ScreenKind, classify
from bglm.toolkit.ocr_reader import recognize

DATA = Path("datasets/raw/wingspan/feasibility")
ROWS = (layout.CUBE_ROW_Y, *layout.FOOD_ROWS_Y)


def ocr_label(image: np.ndarray, y: int) -> tuple[str, float] | None:
    lines = recognize(image, layout.counter_rect(y), 3)
    if len(lines) != 1:
        return None
    text = lines[0].text.strip()
    return (text, lines[0].confidence) if text.isdigit() else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--label", action="append", default=[], help="画像名:行(0〜5):数")
    args = parser.parse_args()

    samples: dict[str, list[np.ndarray]] = collections.defaultdict(list)
    manual = {(n, int(r)): v for n, r, v in (s.split(":") for s in args.label)}
    for path in sorted(DATA.glob("[0-9]*.png")):
        loaded = cv2.imread(str(path))
        if loaded is None:
            continue
        image = np.asarray(loaded, dtype=np.uint8)
        if classify(image).kind is not ScreenKind.MAT:
            continue
        for row, y in enumerate(ROWS):
            label = manual.get((path.stem, row))
            if label is None:
                got = ocr_label(image, y)
                if got is None or got[1] < 0.9:
                    continue
                label = got[0]
            glyphs = segment_glyphs(image, layout.counter_rect(y))
            if len(glyphs) == len(label):
                for digit, glyph in zip(label, glyphs, strict=True):
                    samples[digit].append(glyph)
    report = {d: len(v) for d, v in sorted(samples.items())}
    print(json.dumps(report, ensure_ascii=False))
    missing = sorted(set("0123456789") - set(samples))
    if missing:
        print("正解が集まらなかった桁:", missing)
    if args.dry_run:
        return
    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    for digit, glyphs in samples.items():
        median = np.median(np.stack(glyphs), axis=0).astype(np.uint8)
        assert median.shape == (GLYPH_SIZE[1], GLYPH_SIZE[0])
        cv2.imwrite(str(TEMPLATE_DIR / f"{digit}.png"), median)


if __name__ == "__main__":
    main()
