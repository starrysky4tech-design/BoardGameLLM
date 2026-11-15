"""共有の OCR(toolkit/ocr_reader.py)のテスト。偽のエンジンで、領域の拡大と座標の戻し、モデルの選択を確かめる。"""

import numpy as np
import pytest

from bglm.toolkit import ocr_reader


class FakeEngine:
    """決めた結果を返す。呼ばれた画像の大きさを記録する。"""

    def __init__(self, result: list[tuple[list[list[float]], str, float]] | None) -> None:
        self.result = result
        self.shapes: list[tuple[int, ...]] = []

    def __call__(
        self, crop: np.ndarray
    ) -> tuple[list[tuple[list[list[float]], str, float]] | None, None]:
        self.shapes.append(crop.shape)
        return self.result, None


def box_at(top: float, left: float = 0.0) -> list[list[float]]:
    return [[left, top], [left + 10, top], [left + 10, top + 8], [left, top + 8]]


@pytest.fixture
def image() -> np.ndarray:
    return np.zeros((1080, 2432, 3), dtype=np.uint8)


def test_recognize_scales_the_region_and_maps_back_to_the_image(
    monkeypatch: pytest.MonkeyPatch, image: np.ndarray
) -> None:
    engine = FakeEngine([(box_at(40.0, left=60.0), "Dog rolled 8", 0.97)])
    monkeypatch.setattr(ocr_reader, "get_engine", lambda rec_model=None: engine)
    lines = ocr_reader.recognize(image, (100, 200, 300, 400), 2)
    assert engine.shapes == [(400, 400, 3)]  # 200 x 200 の領域を 2 倍
    assert lines == [
        ocr_reader.RawLine(y=40.0 / 2 + 200, text="Dog rolled 8", confidence=0.97, x=60.0 / 2 + 100)
    ]


def test_recognize_returns_empty_when_nothing_is_read(
    monkeypatch: pytest.MonkeyPatch, image: np.ndarray
) -> None:
    # RapidOCR は、何も読めないと None を返す
    monkeypatch.setattr(ocr_reader, "get_engine", lambda rec_model=None: FakeEngine(None))
    assert ocr_reader.recognize(image, (0, 0, 50, 50), 1) == []


def test_recognize_passes_the_recognition_model(
    monkeypatch: pytest.MonkeyPatch, image: np.ndarray
) -> None:
    seen: list[str | None] = []

    def fake_get_engine(rec_model: str | None = None) -> FakeEngine:
        seen.append(rec_model)
        return FakeEngine([])

    monkeypatch.setattr(ocr_reader, "get_engine", fake_get_engine)
    ocr_reader.recognize(image, (0, 0, 50, 50), 1)
    ocr_reader.recognize(image, (0, 0, 50, 50), 1, rec_model="models/ocr/japan.onnx")
    assert seen == [None, "models/ocr/japan.onnx"]


def test_engine_is_loaded_once_per_model() -> None:
    assert (
        ocr_reader.get_engine.cache_info().maxsize is None
    )  # `functools.cache`(モデルごとに 1 回)
