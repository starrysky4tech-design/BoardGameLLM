"""認識のテンプレート(Git管理外の assets/kahuna/templates/)の読み込み。

テンプレートはゲームの画面の切り出しなので、リポジトリには含めない(docs/04)。
作り方は scripts/kahuna/build_templates.py にある。
"""

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray

from bglm.core.errors import ConfigError
from bglm.plugins.kahuna.logic.models import BoardDef, Player, default_board

DEFAULT_DIR = Path(__file__).resolve().parents[5] / "assets" / "kahuna" / "templates"
DIGIT_CONTEXTS = ("deck", "score", "round")
DIALOG_NAMES = ("continue", "next", "winner_me", "winner_draw")


def _read(path: Path, flags: int) -> NDArray[np.uint8]:
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), flags)
    if image is None:
        raise ConfigError(f"テンプレートを読めない: {path}")
    return np.asarray(image, dtype=np.uint8)


@dataclass(frozen=True)
class TemplateSet:
    names: dict[int, NDArray[np.uint8]]  # 島の添字 → 場札の名前(グレースケール)
    digits: dict[str, dict[str, list[NDArray[np.uint8]]]]  # 文脈 → 数字 → 形(2値)
    stones: dict[Player, NDArray[np.uint8]]  # 持ち主 → 石の絵(BGR)
    dialogs: dict[str, NDArray[np.uint8]]  # ダイアログのボタンの文字・勝者の表示(グレースケール)
    anchor: NDArray[np.uint8]  # 位置合わせの基準(「FISHERMAN」の名前。録画の座標で切り出した)

    @classmethod
    def load(cls, directory: Path = DEFAULT_DIR, board: BoardDef | None = None) -> "TemplateSet":
        board = board or default_board()
        if not directory.exists():
            raise ConfigError(
                f"認識のテンプレートが無い: {directory}。"
                "`uv run python -m scripts.kahuna.build_templates` で、記録した画像から作る"
            )
        names = {
            index: _read(directory / "names" / f"{name}.png", cv2.IMREAD_GRAYSCALE)
            for index, name in enumerate(board.islands)
        }
        digits: dict[str, dict[str, list[NDArray[np.uint8]]]] = {}
        for context in DIGIT_CONTEXTS:
            found: dict[str, list[NDArray[np.uint8]]] = {}
            for path in sorted((directory / "digits" / context).glob("*.png")):
                found.setdefault(path.stem.split("_")[0], []).append(
                    _read(path, cv2.IMREAD_GRAYSCALE)
                )
            digits[context] = found
        stones = {
            Player.ME: _read(directory / "stones" / "me.png", cv2.IMREAD_COLOR),
            Player.OPPONENT: _read(directory / "stones" / "opponent.png", cv2.IMREAD_COLOR),
        }
        dialogs = {
            name: _read(directory / "dialogs" / f"{name}.png", cv2.IMREAD_GRAYSCALE)
            for name in DIALOG_NAMES
        }
        anchor = _read(directory / "anchor" / "fisherman.png", cv2.IMREAD_GRAYSCALE)
        return cls(names=names, digits=digits, stones=stones, dialogs=dialogs, anchor=anchor)
