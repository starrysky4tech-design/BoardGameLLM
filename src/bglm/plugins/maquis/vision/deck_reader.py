"""山札の画面を開いて、捨札の先頭(最も新しく引かれた)カードを読み、閉じる。

巡回は配置のたびに出るが、どのカードが引かれたかは盤だけでは決まらない(複数のカードが同じ地点に出うる)。
そこで、巡回が増えたときに、山札ボタンで画面を開いて捨札の先頭を読む(実機: 捨札は新しい順に左から並ぶ)。
画面を開く・閉じるは入力を送るので、盤を確認できた後にだけ呼ぶ。開けなかった・閉じられなかったときは、
それ以上入力を送らず、理由を返す(呼び出し側が止まる)。
"""

import time
from collections.abc import Callable
from dataclasses import dataclass

from bglm.core.models import Point, Tap
from bglm.core.protocols import GameIo
from bglm.plugins.maquis.logic.patrol import PatrolCard
from bglm.plugins.maquis.vision import layout
from bglm.plugins.maquis.vision.cards import read_discard_top
from bglm.plugins.maquis.vision.screens import ScreenKind, classify_screen
from bglm.toolkit.waiting import poll

OPEN_TRIES = 4
CLOSE_TRIES = 4
WAIT_SEC = 0.7


@dataclass(frozen=True)
class DiscardRead:
    card: PatrolCard | None  # 先頭のカード。読めなければ、または捨札が空なら None
    confidence: float
    empty: bool = False  # 捨札にカードが無い
    problem: str | None = None  # deck_not_open / deck_not_closed / unreadable_card


class DeckReader:
    def __init__(self, sleep: Callable[[float], None] = time.sleep) -> None:
        self._sleep = sleep

    def read_discard_top(self, io: GameIo) -> DiscardRead:
        io.perform(Tap(Point(*layout.DECK_BUTTON)))
        frame, opened = poll(
            io.capture,
            lambda f: classify_screen(f.image) is ScreenKind.DECK,
            tries=OPEN_TRIES,
            wait_sec=WAIT_SEC,
            sleep=self._sleep,
            wait_first=True,
        )
        if not opened:
            return DiscardRead(None, 0.0, problem="deck_not_open")
        card, confidence, present = read_discard_top(frame.image)
        io.perform(Tap(Point(*layout.DECK_BACK)))
        _, closed = poll(
            io.capture,
            lambda f: classify_screen(f.image) is ScreenKind.BOARD,
            tries=CLOSE_TRIES,
            wait_sec=WAIT_SEC,
            sleep=self._sleep,
            wait_first=True,
        )
        if not closed:
            return DiscardRead(None, confidence, problem="deck_not_closed")
        if not present:
            return DiscardRead(None, confidence, empty=True)
        if card is None:
            return DiscardRead(None, confidence, problem="unreadable_card")
        return DiscardRead(card, confidence)
