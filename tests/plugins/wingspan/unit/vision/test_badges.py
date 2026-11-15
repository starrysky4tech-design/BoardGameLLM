"""札の右下のバッジ(蓄えた餌、差し込んだ札)のテスト。実画面の正解は、画像を目視した値。

注意: しきい値は同じ保存画面群で測った(学習データ内の確認)。バッジが両方ある札や 2 桁の数は、まだ画面が無い。
"""

from pathlib import Path

import cv2
import numpy as np
import pytest

from bglm.plugins.wingspan.logic.models import Habitat
from bglm.plugins.wingspan.vision.badges import Badge, BadgeKind, read_badge

F, G, W = Habitat.FOREST, Habitat.GRASSLAND, Habitat.WETLAND
DATA = Path("datasets/raw/wingspan/feasibility")
needs_real = pytest.mark.skipif(not (DATA / "274.png").exists(), reason="実画面が無い(Git 管理外)")


def test_blank_card_has_no_badge() -> None:
    assert read_badge(np.full((1080, 2432, 3), 200, dtype=np.uint8), F, 0) is None


@needs_real
@pytest.mark.parametrize(
    ("name", "habitat", "column", "expected"),
    [
        # 164a(森林): ムナジロゴジュウカラ、ヒガシハイエボシガラ、ドングリキツツキ、ノドジロハリオアマツバメ
        ("164a", F, 0, Badge(BadgeKind.CACHED, 3)),
        ("164a", F, 1, Badge(BadgeKind.CACHED, 3)),
        ("164a", F, 2, Badge(BadgeKind.CACHED, 1)),
        ("164a", F, 3, Badge(BadgeKind.TUCKED, 1)),
        ("131_mat", F, 0, Badge(BadgeKind.CACHED, 1)),
        ("131_mat", F, 1, Badge(BadgeKind.CACHED, 1)),
        ("253_t5", F, 0, Badge(BadgeKind.CACHED, 2)),  # 相手の盤
        # バッジの無い札(鳥の絵の暗い画素を桁と取り違えない)
        ("274", F, 0, None),
        ("274", W, 0, None),
        ("297_hand6", F, 0, None),
        ("131_mat", G, 0, None),
        ("164a", G, 0, None),
    ],
)
def test_real_screens_badges(
    name: str, habitat: Habitat, column: int, expected: Badge | None
) -> None:
    image = cv2.imread(str(DATA / f"{name}.png"))
    assert read_badge(image, habitat, column) == expected
