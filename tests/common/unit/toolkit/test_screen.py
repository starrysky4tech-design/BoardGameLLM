import numpy as np

from bglm.toolkit.screen import LANDSCAPE_SIZE, has_size


def test_landscape_image_has_the_default_size() -> None:
    width, height = LANDSCAPE_SIZE
    assert has_size(np.zeros((height, width, 3), np.uint8))


def test_portrait_image_is_not_landscape() -> None:
    width, height = LANDSCAPE_SIZE
    assert not has_size(np.zeros((width, height, 3), np.uint8))


def test_other_size_is_checked_against_the_given_size() -> None:
    image = np.zeros((10, 20), np.uint8)
    assert not has_size(image)
    assert has_size(image, (20, 10))
