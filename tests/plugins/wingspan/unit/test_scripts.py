"""対局の開始・後始末の道具のテスト。--yes が無ければ何も押さないこと、画面の文言の判別を確かめる。"""

from pathlib import Path

import cv2
import pytest
from scripts.wingspan import finish_game, start_game

from bglm.plugins.wingspan.vision.ocr import JAPANESE_REC_MODEL, japanese_reader

DATA = Path("datasets/raw/wingspan/feasibility")


def test_start_game_refuses_without_yes(monkeypatch: pytest.MonkeyPatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("sys.argv", ["start_game"])
    assert start_game.main() == 2  # 入力を送らずに終わる(AdbDevice も作らない)
    assert "--yes" in capsys.readouterr().out


def test_finish_game_refuses_to_save(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["finish_game", "--save"])
    assert finish_game.main() == 2


@pytest.mark.skipif(
    not JAPANESE_REC_MODEL.exists() or not (DATA / "002_menu.png").exists(),
    reason="日本語の認識モデルまたは実画面が無い(Git 管理外)",
)
@pytest.mark.parametrize(
    ("name", "phrase", "expected"),
    [
        ("002_menu", "保護区の記録", True),
        ("002_menu", "アチーブメント", True),
        ("003_play", "あなたのゲーム", True),
        ("004_custom", "目的ボード", True),
        ("289", "保護区の記録", False),  # 対局中の画面はメインメニューではない
        ("004_custom", "保護区の記録", False),
    ],
)
def test_screen_phrases(name: str, phrase: str, expected: bool) -> None:
    image = cv2.imread(str(DATA / f"{name}.png"))
    text = " ".join(japanese_reader(scale=1)(image, start_game.FULL))
    assert start_game.has(text, phrase) is expected
