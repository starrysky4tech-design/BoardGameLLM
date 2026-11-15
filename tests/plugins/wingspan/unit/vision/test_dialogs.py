"""ダイアログの種別の判別のテスト。OCR の文字列は、保存画面を日本語の認識モデルで読んだ実測(崩れ方もそのまま)。"""

from pathlib import Path

import cv2
import pytest

from bglm.plugins.wingspan.vision.dialogs import (
    DIALOG_SCALE,
    DialogKind,
    classify_dialog_text,
    is_skip_confirm,
    parse_turn_header,
    read_dialog,
)
from bglm.plugins.wingspan.vision.ocr import JAPANESE_REC_MODEL, japanese_reader

K = DialogKind
DATA = Path("datasets/raw/wingspan/feasibility")

MEASURED = [
    # 手番の開始(相手の行動の案内つきも)
    (
        "マツグミ / ラウンド2/4 / 残り6手番 / メリカヤマセミ / タップして手番を開始する。 / 野鳥",
        K.TURN_START,
    ),
    (
        "マツグミ / ラウンド2/4 / 残り6手番 / イスカ / 各プレイヤーは共通在庫からを1個 / すつ獲得する。 / タップして手番を開始する。",
        K.TURN_START,
    ),
    ("ラウンド1/4 / 残り8手番 / にある / タップして手番を開始する。 / 野鳥調査員", K.TURN_START),
    # ラウンドの採点
    (
        "ラウンド1 / にある / 4361のセッ / ラウンド2 / をもつ / ラウンド3ら / ラウンド4 / 総合スコア：ロ5雪り00白の",
        K.ROUND_SCORE,
    ),
    (
        "ラウンド1 / にある4_ / ラウンド25 / ラウンド36 / ラウンド4かゆか / 総合スコア:19034",
        K.ROUND_SCORE,
    ),
    # 終局
    (
        "ムナヅロゴヅユウカラヒガツハイエボツガラドング!ノドヅロハリオアマツ / 鳥ボーナスカードラウンド終了時目的卵鳥力ード上に蓄えた館差し込んだ鳥力ード / メニユー概観リプレイ詳細",
        K.FINAL,
    ),
    ("ナヅロゴジュウカラ / 鳥力ード上に蓄えた館 / 1つにつき1勝利点", K.FINAL),
    # 保存の確認(背景に終局の画面があっても、保存の確認が優先)
    (
        "ナヅロゴジユウカラ / ゲームをセーブして保護区の記録をし / ますか？ / 鳥ボーナスカードラウンド終了時目的卵鳥力ード / メニュー概観リプレイ詳細",
        K.SAVE_PROMPT,
    ),
    # ゲームのメニュー、ストアの案内
    (
        "ユマツグミ / WINGSPAN / では4つのうち / をプレイ再開 / 草原の鳥の設定 / メインメニユー / オンラインメニューに人リ",
        K.GAME_MENU,
    ),
    ("島愛好家のみなさん / ゲーム内ストアで特別なバンドル / ストアに移動", K.STORE),
]


@pytest.mark.parametrize(("text", "kind"), MEASURED)
def test_measured_texts_are_classified(text: str, kind: DialogKind) -> None:
    assert classify_dialog_text(text) is kind


def test_unrelated_text_is_unknown() -> None:
    assert classify_dialog_text("") is K.UNKNOWN
    assert classify_dialog_text("オウゴンヒワ 23cm") is K.UNKNOWN


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("マツグミ / ラウンド2/4 / 残り6手番 / メリカヤマセミ", (2, 6)),
        ("寺：ラウンド1/4 / は共通在庫 / を3個獲残り2手番", (1, 2)),  # 他の文字と混ざっても読める
        ("Cm.ラウンド2/4 / 残り3手番", (2, 3)),
        ("タップして手番を開始する。", (None, None)),
        ("ラウンド5/4 残り手番", (None, None)),
    ],
)
def test_turn_header_is_parsed(text: str, expected: tuple[int | None, int | None]) -> None:
    assert parse_turn_header(text) == expected


needs_ocr = pytest.mark.skipif(
    not JAPANESE_REC_MODEL.exists() or not (DATA / "289.png").exists(),
    reason="日本語の認識モデルまたは実画面が無い(Git 管理外)",
)

REAL = [
    ("289", K.TURN_START, 2, 6),
    ("288", K.TURN_START, 2, 6),  # 相手の行動の案内つき
    ("166a", K.TURN_START, 3, 1),
    ("277_r1end", K.ROUND_SCORE, None, None),
    ("167_r3end", K.ROUND_SCORE, None, None),
    ("176_final", K.FINAL, None, None),
    ("178_menu", K.SAVE_PROMPT, None, None),
    ("266_probe", K.GAME_MENU, None, None),
]


@needs_ocr
@pytest.mark.parametrize(("name", "kind", "round_no", "remaining"), REAL)
def test_real_screens_dialog_kind(
    name: str, kind: DialogKind, round_no: int | None, remaining: int | None
) -> None:
    read = read_dialog(cv2.imread(str(DATA / f"{name}.png")), japanese_reader(scale=DIALOG_SCALE))
    assert (read.kind, read.round_no, read.remaining) == (kind, round_no, remaining)


@needs_ocr
@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("312_skip_dialog", True),  # 「スキップしようとしています / 能力の使用」
        ("310_after_gainfood", True),  # 「まだ餌箱から餌を取ることができます」
        ("034_skip_power", True),
        ("289", False),  # 手番開始のダイアログは、スキップの確認ではない
        ("274", False),  # 盤
    ],
)
def test_real_screens_skip_confirm(name: str, expected: bool) -> None:
    image = cv2.imread(str(DATA / f"{name}.png"))
    assert is_skip_confirm(image, japanese_reader(scale=DIALOG_SCALE)) is expected
