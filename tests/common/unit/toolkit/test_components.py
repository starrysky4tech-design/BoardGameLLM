import numpy as np

from bglm.toolkit.components import component_mask, connected_components


def test_components_report_box_area_and_centroid() -> None:
    # Given: 離れた 2 つの長方形
    mask = np.zeros((20, 30), np.uint8)
    mask[2:6, 3:9] = 1  # 6x4
    mask[10:13, 20:22] = 255  # 2x3(0 以外は前景)

    # When
    components, labels = connected_components(mask)

    # Then
    boxes = sorted((c.x, c.y, c.width, c.height, c.area) for c in components)
    assert boxes == [(3, 2, 6, 4, 24), (20, 10, 2, 3, 6)]
    first = next(c for c in components if c.x == 3)
    assert (first.cx, first.cy) == (5.5, 3.5)
    assert labels.shape == mask.shape


def test_diagonal_pixels_are_connected() -> None:
    mask = np.zeros((5, 5), np.uint8)
    mask[1, 1] = mask[2, 2] = mask[3, 3] = 1
    components, _ = connected_components(mask)
    assert len(components) == 1
    assert components[0].area == 3


def test_empty_mask_has_no_components() -> None:
    components, _ = connected_components(np.zeros((4, 4), np.uint8))
    assert components == []


def test_component_mask_keeps_only_that_component_inside_its_box() -> None:
    # Given: 箱が重なる 2 つの成分(L 字と、その内側の点)
    mask = np.zeros((6, 6), np.uint8)
    mask[1:5, 1] = 1
    mask[4, 1:5] = 1
    mask[2, 3] = 1
    components, labels = connected_components(mask)
    l_shape = max(components, key=lambda c: c.area)

    # When
    part = component_mask(labels, l_shape)

    # Then: 内側の点は含まない
    assert part.shape == (4, 4)
    assert int(part.sum()) == l_shape.area
    assert part[1, 2] == 0
