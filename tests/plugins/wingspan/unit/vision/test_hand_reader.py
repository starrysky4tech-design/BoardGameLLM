"""手札の札名の読み取りのテスト。偽の入出力で、タップの列(開く → 読む → 同じ札をもう一度タップして閉じる)と、
閉じ損ねたときの止まり方を確かめる。実画面の拡大表示(325_zoom_*)は、あれば行ごとの照合を確かめる。
"""

from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import pytest

from bglm.core.models import Frame, InputAction, Point, Tap
from bglm.plugins.wingspan.logic.models import UNKNOWN_CARD
from bglm.plugins.wingspan.vision.hand import card_point
from bglm.plugins.wingspan.vision.hand_reader import read_hand_names, read_zoom_name
from bglm.plugins.wingspan.vision.ocr import JAPANESE_REC_MODEL, japanese_reader

DATA = Path("datasets/raw/wingspan/feasibility")
NAMES = ["コマツグミ", "ハシグロアビ", "野鳥調査員"]


class ToggleIo:
    """札のタップで拡大が開閉する偽の端末。拡大中は、画面が変わる(明るさが違う)。"""

    def __init__(self, stuck_closing: bool = False) -> None:
        self.opened_for: Point | None = None
        self.actions: list[InputAction] = []
        self.stuck_closing = stuck_closing

    def capture(self) -> Frame:
        image = np.zeros((1080, 2432, 3), dtype=np.uint8)
        if self.opened_for is not None:
            image[250:800, 300:1250] = 200  # 拡大した札が覆う
        return Frame.from_image(image, datetime(2026, 11, 14))

    def perform(self, action: InputAction) -> None:
        self.actions.append(action)
        assert isinstance(action, Tap)
        if self.opened_for is None:
            self.opened_for = action.at
        elif action.at == self.opened_for and not self.stuck_closing:
            self.opened_for = None


def test_reads_each_card_by_opening_and_closing_with_the_same_tap() -> None:
    io = ToggleIo()
    spoken = iter([["野鳥調査員"], ["コマツグミ", "効果の文"], ["見知らぬ鳥"]])
    names = read_hand_names(io, 3, lambda *_: next(spoken), NAMES, sleep=lambda _s: None)
    assert names == ["野鳥調査員", "コマツグミ", UNKNOWN_CARD]
    taps = [a.at for a in io.actions if isinstance(a, Tap)]
    expected = [Point(*card_point(3, i)) for i in range(3) for _ in range(2)]
    assert taps == expected  # 各札を 2 回(開く、閉じる)。他の場所は押さない


def test_stops_when_the_zoom_cannot_be_closed() -> None:
    io = ToggleIo(stuck_closing=True)
    result = read_hand_names(io, 3, lambda *_: ["コマツグミ"], NAMES, sleep=lambda _s: None)
    assert result is None
    # 開く 1 回 + 閉じる試行 3 回で止まる。2 枚目へは進まない
    assert len(io.actions) == 4


def test_zoom_name_is_matched_per_line_not_only_on_the_joined_text() -> None:
    lines = ["ハシグロアビ", "起動時:", "湿地の鳥が最も少ない各プレイヤーは"]
    assert read_zoom_name(np.zeros((1080, 2432, 3), dtype=np.uint8), lambda *_: lines, NAMES) == (
        "ハシグロアビ"
    )
    assert read_zoom_name(np.zeros((1080, 2432, 3), dtype=np.uint8), lambda *_: [], NAMES) == (
        UNKNOWN_CARD
    )


needs_real = pytest.mark.skipif(
    not JAPANESE_REC_MODEL.exists() or not (DATA / "325_zoom_0.png").exists(),
    reason="日本語の認識モデルまたは実画面が無い(Git 管理外)",
)


@needs_real
@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("325_zoom_0", "野鳥調査員"),  # ボーナスカード
        ("325_zoom_2", "シロハラミソサザイ"),
        ("325_zoom_4", "ハシグロアビ"),
    ],
)
def test_real_zoom_screens(name: str, expected: str) -> None:
    from bglm.plugins.wingspan.logic.cards import default_table

    image = cv2.imread(str(DATA / f"{name}.png"))
    pool = [*default_table().birds, "野鳥調査員"]
    assert read_zoom_name(image, japanese_reader(scale=2), pool) == expected
