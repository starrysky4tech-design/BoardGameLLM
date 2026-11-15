"""画面の判別(vision/screens.py)のテスト。

参照画像(datasets/eval/monopoly/screens/)は Git 管理外。無い環境では、その画像を使うテストを飛ばす。
期待値は、画面に見えている内容から手で書いた(README.md の表を参照)。
"""

from pathlib import Path

import cv2
import numpy as np
import pytest

from bglm.plugins.monopoly.vision import screens

EVAL_DIR = Path("datasets/eval/monopoly/screens")

# 参照画像 → 期待する画面名(README.md の表と一致させる)
EXPECTED = {
    "auction.png": "auction",
    "bid_keypad.png": "bid_keypad",
    "trade.png": "trade",
    "trade_ai_offer.png": "trade",
    "jail_card_confirm.png": "jail_dialog",
    "jail_bail_confirm.png": "jail_dialog",
    "buy_dialog.png": "buy_dialog",
    "improvements.png": "improvements",
    "zoomed_board.png": "zoomed_board",
    "pause.png": "pause",
    "game_statistics.png": "game_statistics",
    "log_open.png": "log",
    "main_menu.png": "main_menu",
    "my_turn_roll.png": "board_my_turn_roll",
    "my_turn_end_turn.png": "board_my_turn_end",
}


def test_blank_screen_is_unknown() -> None:
    """Given: 一様な灰色の画面 / When: 判別する / Then: 不明を返す(推測で画面名を付けない)"""
    image = np.full((1080, 2432, 3), 128, dtype=np.uint8)

    result = screens.classify(image)

    assert result.name == screens.UNKNOWN


def test_wrong_size_is_unknown() -> None:
    """Given: 原寸と違う大きさの画像 / When: 判別する / Then: 不明を返す"""
    image = np.zeros((720, 1280, 3), dtype=np.uint8)

    result = screens.classify(image)

    assert result.name == screens.UNKNOWN


@pytest.mark.parametrize(("filename", "expected"), sorted(EXPECTED.items()))
def test_reference_screen_is_classified(filename: str, expected: str) -> None:
    """Given: 2026-11-01 の実機の画面 / When: 判別する / Then: 手で付けたラベルの画面名を返す"""
    path = EVAL_DIR / filename
    if not path.exists():
        pytest.skip(f"参照画像が無い: {path}")
    image = cv2.imread(str(path))

    result = screens.classify(image)

    assert result.name == expected
    assert result.confidence >= screens.MATCH_MIN


def test_ai_turn_banner_is_unknown_until_supported() -> None:
    """Given: AI の手番の表示(ボタン無し) / When: 判別する / Then: 対応前は不明を返す

    AI 手番の判別は未対応(テンプレートを作っていない)。対応したら、このテストを期待値の変更に直す。
    """
    path = EVAL_DIR / "ai_turn_banner.png"
    if not path.exists():
        pytest.skip(f"参照画像が無い: {path}")
    image = cv2.imread(str(path))

    result = screens.classify(image)

    assert result.name == screens.UNKNOWN


def test_card_dialog_is_recognized_and_boards_are_not() -> None:
    # Chance のカードと、通常の盤(roll_flow)。後者はカードではない
    classify = screens.classify
    base = Path("datasets/eval/monopoly")
    card = base / "roll_flow" / "card_dialog.png"
    board = base / "roll_flow" / "my_roll_done.png"
    if not card.exists() or not board.exists():
        pytest.skip("実機の画面が無い")
    assert classify(np.asarray(cv2.imread(str(card)), dtype=np.uint8)).name == "card_dialog"
    assert classify(np.asarray(cv2.imread(str(board)), dtype=np.uint8)).name == "board_my_turn_end"


def test_color_is_normal_rejects_a_tinted_screen() -> None:
    base = Path("datasets/eval/monopoly/roll_flow")
    normal = base / "my_roll_done.png"
    if not normal.exists():
        pytest.skip("実機の画面が無い")
    image = np.asarray(cv2.imread(str(normal)), dtype=np.uint8)
    assert screens.color_is_normal(image)
    tinted = image.copy()
    tinted[..., 0] = np.clip(tinted[..., 0].astype(np.int16) + 8, 0, 255).astype(
        np.uint8
    )  # 青を足す
    tinted[..., 2] = np.clip(tinted[..., 2].astype(np.int16) - 47, 0, 255).astype(
        np.uint8
    )  # 赤を減らす
    assert not screens.color_is_normal(tinted)
