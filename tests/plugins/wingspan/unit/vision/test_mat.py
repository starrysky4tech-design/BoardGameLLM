"""全体ボードの読み取りのテスト。合成画像で札の有無と読み取りの流れを、実画面(あれば)で札名の OCR を確かめる。

実画面(datasets/raw/wingspan/feasibility/)と日本語の認識モデル(models/ocr/)は Git 管理外。無い環境では実画面のテストを飛ばす。
"""

from pathlib import Path

import cv2
import numpy as np
import pytest

from bglm.plugins.wingspan.logic.cards import default_table
from bglm.plugins.wingspan.logic.models import UNKNOWN_CARD, Habitat
from bglm.plugins.wingspan.vision.layout import card_rect, name_rect
from bglm.plugins.wingspan.vision.mat import has_card, paper_fraction, read_rows, read_slot
from bglm.plugins.wingspan.vision.ocr import JAPANESE_REC_MODEL, group_lines, japanese_reader
from bglm.toolkit.ocr_reader import RawLine

BIRDS = default_table().birds
F, G, W = Habitat.FOREST, Habitat.GRASSLAND, Habitat.WETLAND
DATA = Path("datasets/raw/wingspan/feasibility")

LEATHER = (45, 70, 110)  # 盤の革の色(BGR)
PAPER = (190, 220, 235)  # 札の紙の色(BGR)


def blank() -> np.ndarray:
    image = np.zeros((1080, 2432, 3), dtype=np.uint8)
    image[:] = LEATHER
    return image


def put_card(image: np.ndarray, habitat: Habitat, column: int) -> None:
    x0, y0, x1, y1 = card_rect(habitat, column)
    image[y0:y1, x0:x1] = PAPER


def test_empty_board_has_no_cards() -> None:
    image = blank()
    assert all(not has_card(image, h, c) for h in (F, G, W) for c in range(5))


def test_card_is_detected_by_paper_color() -> None:
    image = blank()
    put_card(image, F, 0)
    put_card(image, W, 1)
    assert has_card(image, F, 0) and has_card(image, W, 1)
    assert not has_card(image, F, 1) and not has_card(image, G, 0)
    assert paper_fraction(image, card_rect(F, 0)) > 0.95


def test_white_frame_lines_alone_are_not_a_card() -> None:
    # 次に置く枠の白い縁取りは、細い線だけ。札とは区別する
    image = blank()
    x0, y0, x1, y1 = card_rect(G, 2)
    cv2.rectangle(image, (x0 + 20, y0 + 20), (x1 - 20, y1 - 20), (255, 255, 255), 4)
    assert not has_card(image, G, 2)


def test_read_rows_stops_at_first_empty_slot_and_marks_unknown_cards() -> None:
    image = blank()
    for column in range(3):
        put_card(image, F, column)

    names = {name_rect(F, 0): "コマツグミ", name_rect(F, 1): "ヒガシハイエボシガラ"}

    def fake_reader(_image: np.ndarray, box: tuple[int, int, int, int]) -> list[str]:
        return [names.get(box, "")]

    rows = read_rows(image, fake_reader, BIRDS)
    assert [s.name for s in rows[F]] == ["コマツグミ", UNKNOWN_CARD, UNKNOWN_CARD]
    assert rows[F][1].text == "ヒガシハイエボシガラ"  # 表に無い札は、読んだ文字列を記録に残す
    assert rows[G] == [] and rows[W] == []


def test_read_slot_returns_none_without_a_card() -> None:
    assert read_slot(blank(), F, 0, lambda *_: ["コマツグミ"], BIRDS) is None


def test_group_lines_joins_fragments_in_x_order_and_splits_lines() -> None:
    # 実測: 「コマ」「ツグミ」「三」が別の断片で返る。2 行の札名は高さが離れる
    fragments = [
        RawLine(y=139.0, text="ツグミ", confidence=0.7, x=534.0),
        RawLine(y=141.0, text="コマ", confidence=1.0, x=475.0),
        RawLine(y=172.0, text="ガモ", confidence=1.0, x=480.0),
        RawLine(y=140.0, text="三", confidence=1.0, x=606.0),
    ]
    assert group_lines(fragments) == ["コマツグミ三", "ガモ"]


needs_real = pytest.mark.skipif(
    not JAPANESE_REC_MODEL.exists() or not (DATA / "274.png").exists(),
    reason="日本語の認識モデルまたは実画面が無い(Git 管理外)",
)


@needs_real
def test_real_screen_reads_both_birds() -> None:
    # 274.png: 森林 1 列目にコマツグミ、湿地 1 列目にアメリカヤマセミ(RESULT.md §11)。OCR の誤読は札の表との照合で直る
    image = cv2.imread(str(DATA / "274.png"))
    rows = read_rows(image, japanese_reader(), BIRDS)
    assert [s.name for s in rows[F]] == ["コマツグミ"]
    assert rows[G] == []
    assert [s.name for s in rows[W]] == ["アメリカヤマセミ"]


@needs_real
def test_real_screen_marks_cards_missing_from_the_table_as_unknown() -> None:
    # 131_mat.png: 森林にムナジロゴジュウカラとヒガシハイエボシガラ、草原にオウゴンヒワ、湿地にヒメウタスズメ
    image = cv2.imread(str(DATA / "131_mat.png"))
    rows = read_rows(image, japanese_reader(), BIRDS)
    assert [s.name for s in rows[F]] == [UNKNOWN_CARD, UNKNOWN_CARD]  # 表に無い札
    assert [s.name for s in rows[G]] == [UNKNOWN_CARD]
    assert [s.name for s in rows[W]] == ["ヒメウタスズメ"]
