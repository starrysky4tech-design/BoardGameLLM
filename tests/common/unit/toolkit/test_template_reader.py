import numpy as np
import pytest

from bglm.core.models import Reading
from bglm.toolkit.reader_chain import ReaderChain
from bglm.toolkit.template_reader import TemplateReader


def _shape(kind: str) -> np.ndarray:
    image = np.zeros((20, 20), np.uint8)
    if kind == "bar":
        image[:, 8:12] = 255
    elif kind == "box":
        image[4:16, 4:16] = 255
    return image


def test_picks_the_closest_template_with_high_confidence() -> None:
    reader = TemplateReader({"bar": [_shape("bar")], "box": [_shape("box")]})
    reading = reader.read(np.pad(_shape("box"), 3))
    assert reading.value == "box"
    assert reading.confidence > 0.9


def test_confidence_is_low_for_noise() -> None:
    reader = TemplateReader({"bar": [_shape("bar")]})
    noise = np.random.default_rng(0).integers(0, 255, (30, 30), dtype=np.uint8)
    assert reader.read(noise).confidence < 0.5


def test_empty_templates_rejected() -> None:
    with pytest.raises(ValueError):
        TemplateReader({})
    with pytest.raises(ValueError):
        TemplateReader({"a": []})


class _Fixed:
    def __init__(self, value: str, confidence: float) -> None:
        self.reading = Reading(value, confidence)
        self.calls = 0

    def read(self, patch: np.ndarray) -> Reading:
        self.calls += 1
        return self.reading


def test_chain_stops_at_the_first_confident_reader() -> None:
    first, second = _Fixed("a", 0.9), _Fixed("b", 0.99)
    chain = ReaderChain([first, second], min_confidence=0.8)
    assert chain.read(np.zeros((2, 2), np.uint8)).value == "a"
    assert second.calls == 0


def test_chain_falls_through_and_returns_best_when_none_confident() -> None:
    chain = ReaderChain([_Fixed("a", 0.3), _Fixed("b", 0.6)], min_confidence=0.8)
    assert chain.read(np.zeros((2, 2), np.uint8)) == Reading("b", 0.6)


def test_chain_validates_arguments() -> None:
    with pytest.raises(ValueError):
        ReaderChain([], 0.5)
    with pytest.raises(ValueError):
        ReaderChain([_Fixed("a", 1.0)], 1.5)
