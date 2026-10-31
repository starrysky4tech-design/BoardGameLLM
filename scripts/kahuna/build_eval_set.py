"""録画した1ゲームから、Kahuna の評価セットの最初の分を作る(Phase 5)。

出力(Git管理外): datasets/eval/kahuna/session1_NNN.png と .json(正解ラベル)。形式は
`bglm.application.evaluation` の docstring を参照。以降の追加は `bglm eval add` で行う。

ラベルは認識結果の複写である。画面名は、録画の流れ(目視)と一致することを確かめた。
要素のラベルは、`VERIFIED` の各フレームを重ね描き(scripts/kahuna/review_frames.py)と見比べて、
一致すると確認したフレームだけに付ける。
"""

import json
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np

from bglm.plugins.kahuna.vision.describe import describe_recognition
from bglm.plugins.kahuna.vision.recognizer import KahunaRecognizer

SESSION = Path("datasets/raw/kahuna/session1")
OUT = Path("datasets/eval/kahuna")
# 目視で確かめたフレーム番号(session1 の連番)。増やすときは、重ね描きで確かめてから足す
VERIFIED = (18, 38, 72, 100, 124, 146, 165)


def main() -> int:
    recognizer = KahunaRecognizer()
    OUT.mkdir(parents=True, exist_ok=True)
    for i, path in enumerate(sorted(SESSION.glob("f*.png"))):
        case = f"session1_{i:03d}"
        shutil.copyfile(path, OUT / f"{case}.png")
        image = np.asarray(cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR))
        recognition = recognizer.recognize(image)
        label: dict[str, object] = {"screen": recognition.ui.screen}
        if i in VERIFIED:
            label["elements"] = describe_recognition(recognition)
        (OUT / f"{case}.json").write_text(
            json.dumps(label, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    print(f"評価セット: {OUT}(要素ラベルつき {len(VERIFIED)}枚)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
