"""所持金の読み取りを、ラベル付き画像で評価する。

使い方:
  uv run python scripts/monopoly/eval_cash.py            # 局 B(テンプレートの切り出しに使っていない画像)
  uv run python scripts/monopoly/eval_cash.py --group A  # 局 A(切り出し元。参考値)
  uv run python scripts/monopoly/eval_cash.py --cv       # 局 A を、組(自分, AI)ごとに除いた交差検証
"""

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray

from bglm.plugins.monopoly.vision.cash import (
    AI_X,
    SELF_X,
    UNKNOWN,
    CashReading,
    Glyphs,
    extract_glyphs,
    read_cash,
    read_glyphs,
)
from bglm.toolkit.template_reader import TemplateReader

ROOT = Path("datasets/eval/monopoly/cash")
SAME_PIXELS = 12


@dataclass(frozen=True)
class Label:
    key: str
    me: int | None
    ai: int | None
    status: str


@dataclass(frozen=True)
class Row:
    key: str
    side: str
    truth: int
    got: CashReading


def load(group: str) -> list[Label]:
    raw = json.loads((ROOT / "labels.json").read_text(encoding="utf-8"))
    return [
        Label(key, info["self"], info["ai"], info["status"])
        for key, info in sorted(raw.items())
        if key.startswith(group + "/")
    ]


def image_of(label: Label) -> NDArray[np.uint8]:
    image = cv2.imread(str(ROOT / label.key))
    if image is None:
        raise FileNotFoundError(label.key)
    return np.asarray(image, dtype=np.uint8)


def truths(label: Label) -> list[tuple[str, int]]:
    pairs = (("self", label.me), ("ai", label.ai))
    return [(side, value) for side, value in pairs if value is not None]


def report(rows: list[Row], title: str) -> None:
    counts: Counter[str] = Counter()
    for row in rows:
        if row.got.value is None:
            counts["unknown"] += 1
        elif row.got.value == row.truth:
            counts["correct"] += 1
        else:
            counts["WRONG"] += 1
            print("  WRONG", row.key, row.side, row.truth, row.got)
    print(f"[{title}] {dict(counts)} total={len(rows)}")
    for row in [r for r in rows if r.got.value is None][:20]:
        print("  unknown", row.key, row.side, row.truth)


def evaluate(group: str) -> None:  # group は "A"、"B"、"C" のいずれか
    rows = []
    for label in load(group):
        if label.status != "ok":
            continue
        pair = read_cash(image_of(label))
        got = {"self": pair.me, "ai": pair.ai}
        rows += [Row(label.key, side, value, got[side]) for side, value in truths(label)]
    report(rows, f"group {group}")


def _add(store: dict[str, list[NDArray[np.uint8]]], text: str, glyphs: Glyphs) -> None:
    for char, glyph in zip(text, glyphs.digits, strict=True):
        variants = store.setdefault(char, [])
        if all(int(np.count_nonzero(v != glyph)) > SAME_PIXELS for v in variants):
            variants.append(glyph)


def cross_validate() -> None:
    entries: list[tuple[Label, str, int, Glyphs | None]] = []
    for label in load("A"):
        if label.status != "ok":
            continue
        image = image_of(label)
        x_ranges = {"self": SELF_X, "ai": AI_X}
        for side, value in truths(label):
            entries.append((label, side, value, extract_glyphs(image, x_ranges[side])))
    rows = []
    for label, side, truth, glyphs in entries:
        store: dict[str, list[NDArray[np.uint8]]] = {}
        for other, _, value, other_glyphs in entries:
            same_pair = (other.me, other.ai) == (label.me, label.ai)
            if (
                same_pair
                or other_glyphs is None
                or len(other_glyphs.digits) != len(str(abs(value)))
            ):
                continue
            _add(store, str(abs(value)), other_glyphs)
        if not set(str(abs(truth))) <= set(store):
            continue  # 除くと、その数字のテンプレートが無くなる組は評価できない
        got = read_glyphs(glyphs, TemplateReader(store)) if glyphs else UNKNOWN
        rows.append(Row(label.key, side, truth, got))
    report(rows, "cross-validation A")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", default="B")
    parser.add_argument("--cv", action="store_true")
    args = parser.parse_args()
    if args.cv:
        cross_validate()
    else:
        evaluate(args.group)
