"""確認済みの正解ラベル(datasets/eval/hive/*.json)と、認識の結果を比べる(docs/01 の盤面認識の正答率)。

要素単位の正答率 = 正しく読めた駒(位置、側、種類がすべて一致)の数 ÷ 正解の駒の数。
読み取り結果の screen が正解と一致するかも数える。reviewed が true のラベルだけを使う。

使い方:
    uv run python -m scripts.hive.eval_recognition datasets/raw/hive/feasibility datasets/eval/hive
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray

from bglm.plugins.hive.logic.models import HexCoord, Piece
from bglm.plugins.hive.vision.recognizer import read_board
from bglm.plugins.hive.vision.screens import screen_of
from scripts.hive.build_review import _shift


def _truth(label: dict[str, object]) -> dict[HexCoord, tuple[str, str]]:
    out: dict[HexCoord, tuple[str, str]] = {}
    for t in label["tops"]:  # type: ignore[attr-defined]
        out[HexCoord(t["q"], t["r"])] = (t["color"], t["kind"])
    return out


def _predicted(tops: dict[HexCoord, Piece]) -> dict[HexCoord, tuple[str, str]]:
    return {at: (p.color.name, p.kind.value) for at, p in _shift(tops).items()}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("src", type=Path)
    parser.add_argument("labels", type=Path)
    args = parser.parse_args()
    total = correct = false_pos = screens_ok = screens = 0
    for path in sorted(args.labels.glob("*.json")):
        label: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
        # 確認済み(reviewed)か、読み取りとは別に書いた正解(method が blind)だけを使う
        if not label.get("reviewed") and not str(label.get("method", "")).startswith("blind"):
            continue
        image_path = args.src / str(label["file"])
        loaded = cv2.imread(str(image_path))
        if loaded is None:
            print(f"{image_path.name}: 画像が無い")
            continue
        image: NDArray[np.uint8] = loaded.astype(np.uint8)
        reading = read_board(image)
        screens += 1
        screens_ok += int(screen_of(bool(reading.tops), reading.problems).value == label["screen"])
        if label["screen"] != "board":
            continue
        truth = _truth(label)
        pred = _predicted(reading.tops)
        hits = sum(1 for at, v in truth.items() if pred.get(at) == v)
        total += len(truth)
        correct += hits
        false_pos += sum(1 for at in pred if at not in truth)
        wrong = [f"{at.q},{at.r}" for at, v in truth.items() if pred.get(at) != v]
        if wrong or set(pred) != set(truth):
            print(
                f"{path.stem}: 誤り={wrong} 余分={[f'{a.q},{a.r}' for a in pred if a not in truth]}"
            )
    rate = correct / total if total else 0.0
    print(f"画面の種類 一致 {screens_ok}/{screens}")
    print(f"要素の正答率 {correct}/{total} = {rate:.3f}(余分な読み取り {false_pos})")


if __name__ == "__main__":
    main()
