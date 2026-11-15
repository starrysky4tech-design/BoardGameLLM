"""Log と枠の読み取りが、共有の OCR エンジン(toolkit/ocr_reader.py)を使うことのテスト。偽のエンジンで確かめる。"""

import numpy as np
import pytest

from bglm.plugins.monopoly.vision.dialog_reader import BoxOcr
from bglm.plugins.monopoly.vision.log_reader import PANEL, LogOcr
from bglm.toolkit import ocr_reader


class FakeEngine:
    """決めた結果を返す。呼ばれた画像の大きさを記録する。"""

    def __init__(self, result: list[tuple[list[list[float]], str, float]]) -> None:
        self.result = result
        self.shapes: list[tuple[int, ...]] = []

    def __call__(self, crop: np.ndarray) -> tuple[list[tuple[list[list[float]], str, float]], None]:
        self.shapes.append(crop.shape)
        return self.result, None


def box_at(top: float, left: float = 0.0) -> list[list[float]]:
    return [[left, top], [left + 10, top], [left + 10, top + 8], [left, top + 8]]


@pytest.fixture
def image() -> np.ndarray:
    return np.zeros((1080, 2432, 3), dtype=np.uint8)


def test_log_ocr_and_box_ocr_use_the_same_engine(
    monkeypatch: pytest.MonkeyPatch, image: np.ndarray
) -> None:
    engine = FakeEngine([(box_at(60.0), "B", 0.9), (box_at(10.0), "A", 0.95)])
    monkeypatch.setattr(ocr_reader, "get_engine", lambda rec_model=None: engine)
    log_lines = LogOcr().read(image)
    box_texts = BoxOcr().read_box(image, (0, 0, 100, 50))
    assert len(engine.shapes) == 2  # どちらの読み取りも、同じエンジンを使った
    assert [line.text for line in log_lines] == ["A", "B"]  # Log は、上から順に並べる
    assert [t.text for t in box_texts] == ["B", "A"]  # 枠の読み取りは、エンジンの返す順のまま
    assert log_lines[0].y == pytest.approx(10.0 / 2 + PANEL[1])
