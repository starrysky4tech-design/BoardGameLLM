"""札名の照合のテスト。OCR の誤読は、RESULT.md §6 の実測(日本語の認識モデル)から取った。"""

import pytest

from bglm.plugins.wingspan.logic.cards import default_table
from bglm.plugins.wingspan.vision.names import (
    fold,
    match_card,
    match_name,
    similarity,
)

TABLE = default_table()
NAMES = list(TABLE.birds)


@pytest.mark.parametrize(
    ("ocr", "expected"),
    [
        ("ヒメウタスズメ", "ヒメウタスズメ"),  # 誤読なし
        ("クロハサミアツサツ", "クロハサミアジサシ"),  # ジ→ツ、シ→ツ
        ("イヌワツ", "イヌワシ"),  # シ→ツ
        ("アメリカトキユウ", "アメリカトキコウ"),  # コ→ユ
        ("クロズキソアメリカムシクイ", "クロズキンアメリカムシクイ"),  # ン→ソ
        ("ノドアカ ハチドリ", None),  # 表に無い札(空白は無視されるが、近い札が無い)
    ],
)
def test_ocr_misreads_are_folded(ocr: str, expected: str | None) -> None:
    found = match_name(ocr, NAMES)
    assert (found.name if found else None) == expected


def test_unknown_card_is_not_forced_onto_a_similar_known_card() -> None:
    # 表に無い札(ヒガシハイエボシガラ、キタホオジロガモ)を、似た名前の札へ当てはめない
    assert match_name("ヒガシハイエボシガラ", NAMES) is None
    assert match_name("キタホオジロガモ", NAMES) is None
    assert match_name("ヒガンハイエボンガラ", NAMES) is None  # その OCR の誤読も


def test_empty_or_symbol_only_text_is_not_a_name() -> None:
    assert match_name("", NAMES) is None
    assert match_name(" ・ー ", NAMES) is None  # 記号だけでも、どの札にも当てはまらない
    assert match_name("   ", NAMES) is None


def test_two_line_name_is_joined_by_ignoring_spaces() -> None:
    # 札名は長いと 2 行に分かれる(例: アカハシリュウキュウ / ガモ)。行をつないで渡せる
    found = match_name("アカハシリュウキュウ ガモ", NAMES)
    assert found is not None and found.name == "アカハシリュウキュウガモ"


def test_ambiguous_match_is_rejected_by_margin() -> None:
    # 畳むと同じ形になる 2 つの名前は、どちらか決められない
    assert match_name("アシ", ["アシ", "アツ"]) is None
    assert match_name("アシ", ["アシ", "ホカノナマエ"]) is not None


def test_fold_removes_dakuten_and_unifies_confusables() -> None:
    assert fold("ジ") == fold("シ") == fold("ツ")
    assert fold("ッ") == fold("ツ")  # 小さい仮名
    assert fold("ミサゴ ") == fold("ミサコ") == fold("ミサユ")
    assert similarity("ミサゴ", "ミサゴ") == 1.0


def test_wingspan_and_points_must_agree_with_the_table() -> None:
    # 名前が読めても、翼長・点が表の値と違えば別の札の疑いで None
    assert match_card("イヌワシ", TABLE.birds, wingspan_cm=201, points=8) is not None
    assert match_card("イヌワシ", TABLE.birds, wingspan_cm=18) is None
    assert match_card("イヌワシ", TABLE.birds, points=3) is None
    assert match_card("イヌワシ", TABLE.birds) is not None  # 読めていない値は比べない
