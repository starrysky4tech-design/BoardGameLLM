"""画面の種類の判定(docs/04「hive/vision/screens.py」)。盤を読んだ結果から、今の画面が盤かどうかを分ける。

- BOARD: 盤が見えていて、すべてのマスを読めた
- NO_BOARD: マスが1つも無い(タイトル、説明、メニューの全面など)
- OVERLAY: マスは見えるが、地の一部が覆われている、または駒の種類が読めない(メニューや選択の表示が重なった)
- GRID_MISMATCH: マスは見えるが格子に合わない(盤の拡大・移動、重なった表示)

判定は読み取りの結果(マスの有無と問題の一覧)だけで行う。循環 import を避けるため、読み取りそのものは持たない。
"""

from collections.abc import Sequence
from enum import Enum


class ScreenKind(Enum):
    BOARD = "board"
    NO_BOARD = "no_board"
    OVERLAY = "overlay"
    GRID_MISMATCH = "grid_mismatch"


def screen_of(has_tops: bool, problems: Sequence[str]) -> ScreenKind:
    if "grid_mismatch" in problems:
        return ScreenKind.GRID_MISMATCH
    if not has_tops and not problems:
        return ScreenKind.NO_BOARD
    if problems:
        return ScreenKind.OVERLAY
    return ScreenKind.BOARD
