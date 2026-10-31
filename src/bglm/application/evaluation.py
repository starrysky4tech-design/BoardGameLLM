"""認識の正答率の計測(EvalHarness)。

評価セットは `<root>/<game>/<case_id>.png` と、正解ラベル `<case_id>.json`(docs/02「データ保存形式」):

    {"screen": "my_turn", "elements": {"hand": ["ALOA"], "sticks[0]": "M", ...}}

`screen` は全件、`elements` は人が確かめた件だけに付ける。要素の値は、プラグインの
`describe_recognition` が返す形(`RecognitionDescriber`)。同じ種類の要素("sticks[3]")は
添字の前の名前で集計する。
"""

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from bglm.application.game_io import ReplayGameIo
from bglm.core.errors import BglmError
from bglm.core.models import Frame
from bglm.core.protocols import GamePlugin, ImageStore, RecognitionDescriber

CASE_ID = re.compile(r"[A-Za-z0-9_.-]+")
RETRY_FRAMES = 4  # 読めないときの取り直し用に、同じ画像を繰り返し返す


class EvalError(BglmError):
    pass


@dataclass
class EvalReport:
    hits: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    totals: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    misses: list[str] = field(default_factory=list)
    cases: int = 0

    def record(self, group: str, ok: bool) -> None:
        self.totals[group] += 1
        self.hits[group] += int(ok)

    def rate(self, group: str) -> float:
        return self.hits[group] / self.totals[group]

    @property
    def worst_rate(self) -> float:
        return min((self.rate(g) for g in self.totals), default=1.0)

    def passes(self, target: float) -> bool:
        return bool(self.totals) and self.worst_rate >= target


def _group(key: str) -> str:
    return key.split("[", 1)[0]


class EvalHarness:
    def __init__(self, plugin: GamePlugin[Any, Any], root: Path, images: ImageStore) -> None:
        if not isinstance(plugin, RecognitionDescriber):
            raise EvalError(f"プラグイン {plugin.name!r} は describe_recognition を持たない")
        self._plugin = plugin
        self._describer: RecognitionDescriber[Any] = plugin
        self._dir = root / plugin.name
        self._images = images

    def evaluate(self) -> EvalReport:
        labels = sorted(self._dir.glob("*.json"))
        if not labels:
            raise EvalError(f"評価セットが空: {self._dir}")
        report = EvalReport()
        for label_path in labels:
            case = label_path.stem
            label = json.loads(label_path.read_text(encoding="utf-8"))
            image = self._images.read(label_path.with_suffix(".png"))
            recognition = self._recognize(image)
            report.cases += 1
            ok = recognition.ui.screen == label["screen"]
            report.record("screen", ok)
            if not ok:
                report.misses.append(
                    f"{case}: 画面 {recognition.ui.screen} (正解 {label['screen']})"
                )
            expected: dict[str, Any] = label.get("elements", {})
            actual = self._describer.describe_recognition(recognition)
            for key, value in expected.items():
                ok = actual.get(key) == value
                report.record(_group(key), ok)
                if not ok:
                    report.misses.append(f"{case}: {key} {actual.get(key)!r} (正解 {value!r})")
        return report

    def add_case(self, game_image: NDArray[np.uint8], case_id: str, label: dict[str, Any]) -> Path:
        """画像と正解ラベルを追加する。同じ case_id は上書きしない。"""
        if not CASE_ID.fullmatch(case_id):
            raise EvalError(f"case_id が不正: {case_id!r}(英数字と _ - . のみ)")
        if "screen" not in label:
            raise EvalError("ラベルに screen が無い")
        png = self._dir / f"{case_id}.png"
        if png.exists():
            raise EvalError(f"同じ case_id が既にある: {case_id}")
        self._images.write(png, game_image)
        png.with_suffix(".json").write_text(
            json.dumps(label, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        return png

    def _recognize(self, image: NDArray[np.uint8]) -> Any:
        frame = Frame.from_image(image, datetime.now())
        return self._plugin.recognizer().observe(ReplayGameIo([frame] * RETRY_FRAMES), None)
