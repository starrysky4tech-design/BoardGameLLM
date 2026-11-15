from pathlib import Path

import cv2
import numpy as np

from bglm.toolkit.images import crop, gray, load_image


def test_load_image_reads_a_path_with_japanese_characters(tmp_path: Path) -> None:
    # Given: 日本語を含むフォルダの PNG(cv2.imread では読めない)
    image = np.zeros((4, 6, 3), np.uint8)
    image[1, 2] = (10, 20, 30)
    path = tmp_path / "画面" / "見本.png"
    path.parent.mkdir()
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    encoded.tofile(path)

    # When
    loaded = load_image(path)

    # Then
    assert loaded is not None
    assert loaded.dtype == np.uint8
    assert np.array_equal(loaded, image)


def test_load_image_in_grayscale(tmp_path: Path) -> None:
    path = tmp_path / "g.png"
    ok, encoded = cv2.imencode(".png", np.full((3, 5), 77, np.uint8))
    assert ok
    encoded.tofile(path)
    loaded = load_image(path, cv2.IMREAD_GRAYSCALE)
    assert loaded is not None
    assert loaded.shape == (3, 5)


def test_load_image_returns_none_for_a_missing_file(tmp_path: Path) -> None:
    assert load_image(tmp_path / "無い.png") is None


def test_load_image_returns_none_for_a_non_image(tmp_path: Path) -> None:
    path = tmp_path / "not_image.png"
    path.write_bytes(b"not a png")
    assert load_image(path) is None


def test_gray_converts_bgr_to_uint8_single_channel() -> None:
    image = np.full((2, 3, 3), 200, np.uint8)
    result = gray(image)
    assert result.shape == (2, 3)
    assert result.dtype == np.uint8
    assert int(result[0, 0]) == 200


def test_crop_uses_x0_y0_x1_y1() -> None:
    image = np.arange(5 * 6).reshape(5, 6).astype(np.uint8)
    part = crop(image, (1, 2, 4, 5))
    assert part.shape == (3, 3)
    assert int(part[0, 0]) == int(image[2, 1])
