"""実行ログの保存と読み戻し。形式の正本は docs/02 の「データ保存形式」。

    <root>/<run_id>/
    ├── run.json
    └── steps/<000001>/{frame_01.png, overlay.png, step.json}

画像は日本語を含むパスでも扱えるよう、cv2.imwrite/imread ではなく imencode/imdecode を使う。
"""

import json
import shutil
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray

from bglm.core.models import Frame, RunSummary, StepRecord, StopReason


def write_png(path: Path, image: NDArray[np.uint8]) -> None:
    ok, buffer = cv2.imencode(".png", image)
    if not ok:
        raise ValueError(f"PNGに符号化できない: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buffer.tobytes())


def read_png(path: Path) -> NDArray[np.uint8]:
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"PNGを復号できない: {path}")
    return np.asarray(image, dtype=np.uint8)


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class RunLogger:
    """1回の実行のログを書く。"""

    def __init__(self, root: Path, run_id: str) -> None:
        self.run_dir = root / run_id
        self.run_id = run_id

    def start(self) -> None:
        """実行ディレクトリを作る。同じ run_id が既にあれば FileExistsError(上書きしない)。"""
        self.run_dir.mkdir(parents=True, exist_ok=False)

    def save_frames(
        self,
        step: int,
        frames: Sequence[Frame],
        overlay: NDArray[np.uint8] | None = None,
    ) -> list[str]:
        """1手で取得した画像を保存し、run_dir からの相対パスを返す。"""
        directory = self.run_dir / "steps" / f"{step:06d}"
        paths: list[str] = []
        for i, frame in enumerate(frames, start=1):
            relative = f"steps/{step:06d}/frame_{i:02d}.png"
            write_png(self.run_dir / relative, frame.image)
            paths.append(relative)
        if overlay is not None:
            write_png(directory / "overlay.png", overlay)
        return paths

    def save_step(self, record: StepRecord) -> None:
        _write_json(
            self.run_dir / "steps" / f"{record.step:06d}" / "step.json", record.to_jsonable()
        )

    def save_summary(self, summary: RunSummary) -> None:
        _write_json(self.run_dir / "run.json", summary.to_jsonable())


def load_summary(run_dir: Path) -> RunSummary:
    data = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    return RunSummary.from_jsonable(data)


def load_steps(run_dir: Path) -> list[StepRecord]:
    """手の順(step番号の昇順)で返す。"""
    paths = sorted((run_dir / "steps").glob("*/step.json"))
    return [StepRecord.from_jsonable(json.loads(p.read_text(encoding="utf-8"))) for p in paths]


def load_frame(run_dir: Path, relative: str) -> Frame:
    """保存した画像を Frame として読む。取得時刻は保存されないため、ファイルの更新時刻で代用する。"""
    path = run_dir / relative
    captured_at = datetime.fromtimestamp(path.stat().st_mtime)
    return Frame.from_image(read_png(path), captured_at)


def _directory_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def prune_runs(root: Path, limit_bytes: int, protect: frozenset[str] = frozenset()) -> list[str]:
    """ログの総量が limit_bytes を超えたら、古くて正常終了した実行から削除する。

    削除するのは run.json があり、stop_reason が GAME_OVER の実行だけ。
    異常停止の実行、実行中(run.json が無い)の実行、protect に挙げた実行は残す。
    削除した run_id を返す。
    """
    if not root.exists():
        return []
    runs = [d for d in root.iterdir() if d.is_dir()]
    total = sum(_directory_size(d) for d in runs)

    candidates: list[tuple[datetime, Path]] = []
    for directory in runs:
        if directory.name in protect or not (directory / "run.json").exists():
            continue
        summary = load_summary(directory)
        if summary.stop_reason is StopReason.GAME_OVER:
            candidates.append((summary.ended_at, directory))

    deleted: list[str] = []
    for _, directory in sorted(candidates, key=lambda c: c[0]):
        if total <= limit_bytes:
            break
        size = _directory_size(directory)
        shutil.rmtree(directory)
        total -= size
        deleted.append(directory.name)
    return deleted


class FsRunReader:
    """`<root>/<run_id>/` のログを読む(RunReader)。"""

    def __init__(self, root: Path) -> None:
        self._root = root

    def has_run(self, run_id: str) -> bool:
        return (self._root / run_id / "steps").exists()

    def steps(self, run_id: str) -> list[StepRecord]:
        return load_steps(self._root / run_id)

    def frame(self, run_id: str, relative: str) -> Frame:
        return load_frame(self._root / run_id, relative)


class PngStore:
    """PNG の読み書き(ImageStore)。日本語を含むパスでも扱える。"""

    def read(self, path: Path) -> NDArray[np.uint8]:
        return read_png(path)

    def write(self, path: Path, image: NDArray[np.uint8]) -> None:
        write_png(path, image)
