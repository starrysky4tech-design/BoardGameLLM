"""Kahuna の手を、タップに変えて実行する。

実機で手順を確かめた手だけを実装する(docs/ideas/Kahuna_アプリ内ルール.md の「操作」):
- 杖コマを置く: 手札のカードをタップ → 照準マークをタップ → 杖コマが置かれたかを確かめる
- 場札を引く: 場札のカードをタップ → 場札のその枠が変わったかを確かめる
- 杖コマを除去する: 2枚を選ぶ → 相手の杖の赤い丸をタップ → 杖が消えたかを確かめる
- 捨てる: カードを選ぶ → DISCARD の位置をタップ → 手札が1枚減ったかを確かめる
- 山札から引く: 山札をタップ → 手札が1枚増えたかを確かめる
- 手番を終える: 右下の手のマーク → 画面が変わったかを確かめる
座標は録画の座標(位置合わせ後)で持ち、タップの直前に取得画像の座標へ直す。
"""

import time
from collections.abc import Callable

import numpy as np
from numpy.typing import NDArray

from bglm.core.models import ExecutionResult, Point, Tap
from bglm.core.protocols import GameIo
from bglm.plugins.kahuna.logic.models import (
    BoardDef,
    DiscardCard,
    DrawDeck,
    DrawMarket,
    KahunaMove,
    KahunaState,
    PassDraw,
    PlaceStick,
    Player,
    RemoveStick,
    default_board,
)
from bglm.plugins.kahuna.vision.alignment import Alignment, aligned_view
from bglm.plugins.kahuna.vision.cards import (
    MARKET_NAME_H,
    MARKET_NAME_Y,
    MARKET_SLOT_W,
    MARKET_SLOT_X,
    CardReading,
    read_hand,
    read_market,
)
from bglm.plugins.kahuna.vision.screens import MY_TURN, OPPONENT_TURN, classify_screen
from bglm.plugins.kahuna.vision.sticks import MAX_DISTANCE, find_blobs
from bglm.plugins.kahuna.vision.templates import TemplateSet

TAP_WAIT_SEC = 1.0  # タップ後の画面が落ち着くまでの待ち

# 録画の座標(位置合わせ後)。実機の2026-10-31の操作で確かめた位置。
DECK_TAP = Point(1066, 1045)  # 山札の中央(ALOA ステージで引けた位置)
END_TURN_TAP = Point(2339, 997)  # 右下の手のマーク
DISCARD_TAP = Point(805, 1007)  # 「DISCARD」の文字(カードを選ぶと出る)


class KahunaExecutor:
    def __init__(
        self,
        templates: TemplateSet | None = None,
        board: BoardDef | None = None,
        *,
        sleep: Callable[[float], None] = time.sleep,
        wait_sec: float = TAP_WAIT_SEC,
    ) -> None:
        self._board = board or default_board()
        self._templates = templates or TemplateSet.load(board=self._board)
        self._sleep = sleep
        self._wait_sec = wait_sec

    def execute(self, io: GameIo, state: KahunaState, move: KahunaMove) -> ExecutionResult:
        match move:
            case PlaceStick():
                return self._place_stick(io, move)
            case DrawMarket():
                return self._draw_market(io, move, state)
            case RemoveStick():
                return self._remove_stick(io, move)
            case DiscardCard():
                return self._discard(io, move)
            case DrawDeck():
                return self._draw_deck(io, state)
            case PassDraw():
                return self._end_turn(io, state)
            case _:
                return ExecutionResult(False, f"未確認の操作: {type(move).__name__}")

    def _is_my_turn(self, image: NDArray[np.uint8], state: KahunaState) -> bool:
        """自分の手番か。手札が0枚の手番は画面から区別できないので、引く操作に限り、手札0枚の状態を信じる。"""
        name = classify_screen(image, self._templates).name
        if name == MY_TURN:
            return True
        return not state.hand and name == OPPONENT_TURN

    def _hand(self, image: NDArray[np.uint8]) -> list[CardReading]:
        return read_hand(image, self._templates)

    def _select_hand_card(
        self, io: GameIo, image_hand: list[CardReading], island: int, alignment: Alignment
    ) -> bool:
        """手札の指定の島のカードを、読み取った位置で押す。無ければ False(押さない)。"""
        matches = [c for c in image_hand if c.island == island]
        if not matches:
            return False
        card = max(matches, key=lambda c: c.score)
        self._tap(io, Point(card.x, card.y), alignment)
        return True

    def _remove_stick(self, io: GameIo, move: RemoveStick) -> ExecutionResult:
        view = self._capture(io)
        if view is None:
            return ExecutionResult(False, "位置合わせの基準が見つからない")
        image, alignment = view
        if classify_screen(image, self._templates).name != MY_TURN:
            return ExecutionResult(False, "自分の手番の画面ではない")
        hand = self._hand(image)
        first, second = move.cards
        if first == second or not (
            any(c.island == first for c in hand) and any(c.island == second for c in hand)
        ):
            return ExecutionResult(False, "除去に必要な2枚が手札に無い")
        self._select_hand_card(io, hand, first, alignment)
        self._select_hand_card(io, hand, second, alignment)
        line = self._board.lines[move.line].position
        self._tap(io, line, alignment)  # 2枚選ぶと出る赤い丸
        after_view = self._capture(io)
        if after_view is None:
            return ExecutionResult(False, "除去の確認の画面で位置合わせできない")
        removed = self._wait_until(io, lambda img: not self._has_opponent_stick(img, line))
        if removed:
            return ExecutionResult(True)
        return ExecutionResult(False, "相手の杖が取り除かれたことを確認できない")

    @staticmethod
    def _has_opponent_stick(image: NDArray[np.uint8], at: Point) -> bool:
        for blob in find_blobs(image):
            near = ((blob.center.x - at.x) ** 2 + (blob.center.y - at.y) ** 2) ** 0.5
            if blob.owner is Player.OPPONENT and near <= MAX_DISTANCE:
                return True
        return False

    def _discard(self, io: GameIo, move: DiscardCard) -> ExecutionResult:
        view = self._capture(io)
        if view is None:
            return ExecutionResult(False, "位置合わせの基準が見つからない")
        image, alignment = view
        if classify_screen(image, self._templates).name != MY_TURN:
            return ExecutionResult(False, "自分の手番の画面ではない")
        hand = self._hand(image)
        if not self._select_hand_card(io, hand, move.card, alignment):
            return ExecutionResult(False, f"手札に {self._board.islands[move.card]} が無い")
        self._tap(io, DISCARD_TAP, alignment)
        after_view = self._capture(io)
        if after_view is None:
            return ExecutionResult(False, "捨てた後の画面で位置合わせできない")
        if self._wait_until(io, lambda img: len(self._hand(img)) == len(hand) - 1):
            return ExecutionResult(True)
        return ExecutionResult(False, "手札が1枚減ったことを確認できない")

    def _draw_deck(self, io: GameIo, state: KahunaState) -> ExecutionResult:
        view = self._capture(io)
        if view is None:
            return ExecutionResult(False, "位置合わせの基準が見つからない")
        image, alignment = view
        if not self._is_my_turn(image, state):
            return ExecutionResult(False, "自分の手番の画面ではない")
        before = len(self._hand(image))
        self._tap(io, DECK_TAP, alignment)
        if self._wait_until(io, lambda img: len(self._hand(img)) == before + 1):
            return ExecutionResult(True)
        return ExecutionResult(False, "山札から引けたことを確認できない")

    def _end_turn(self, io: GameIo, state: KahunaState) -> ExecutionResult:
        view = self._capture(io)
        if view is None:
            return ExecutionResult(False, "位置合わせの基準が見つからない")
        image, alignment = view
        if not self._is_my_turn(image, state):
            return ExecutionResult(False, "自分の手番の画面ではない")
        self._tap(io, END_TURN_TAP, alignment)
        after_view = self._capture(io)
        if after_view is None:
            return ExecutionResult(True)  # 決算などで位置合わせできないのは、手番が変わった証拠
        if classify_screen(after_view[0], self._templates).name == MY_TURN:
            return ExecutionResult(False, "手番が終わったことを確認できない")
        return ExecutionResult(True)

    def _tap(self, io: GameIo, point: Point, alignment: Alignment) -> None:
        """録画の座標の点を、取得画像の座標に直して押す。"""
        io.perform(Tap(alignment.to_screen(point)))
        self._sleep(self._wait_sec)

    def _capture(self, io: GameIo) -> tuple[NDArray[np.uint8], Alignment] | None:
        """録画の座標に揃えた画像と、ずれ。基準が見つからなければ None。"""
        return aligned_view(io.capture().image, self._templates.anchor)

    def _place_stick(self, io: GameIo, move: PlaceStick) -> ExecutionResult:
        view = self._capture(io)
        if view is None:
            return ExecutionResult(False, "位置合わせの基準が見つからない")
        image, alignment = view
        if classify_screen(image, self._templates).name != MY_TURN:
            return ExecutionResult(False, "自分の手番の画面ではない")
        cards = [c for c in read_hand(image, self._templates) if c.island == move.card]
        if not cards:
            return ExecutionResult(False, f"手札に {self._board.islands[move.card]} が無い")
        card = max(cards, key=lambda c: c.score)  # 同じ島のカードが複数なら、確かに読めた方
        line = self._board.lines[move.line]
        self._tap(io, Point(card.x, card.y), alignment)
        self._tap(io, line.position, alignment)
        if self._wait_until(io, lambda img: self._has_own_stick(img, line.position)):
            return ExecutionResult(True)
        return ExecutionResult(False, "杖コマが置かれたことを確認できない")

    def _has_own_stick(self, image: NDArray[np.uint8], at: Point) -> bool:
        for blob in find_blobs(image):
            near = ((blob.center.x - at.x) ** 2 + (blob.center.y - at.y) ** 2) ** 0.5
            if blob.owner is Player.ME and near <= MAX_DISTANCE:
                return True
        return False

    def _wait_until(
        self, io: GameIo, check: Callable[[NDArray[np.uint8]], bool], tries: int = 4
    ) -> bool:
        """画面が落ち着くまで、取り直しながら確かめる(杖や捨て札の表示は少し遅れて出る)。"""
        for _ in range(tries):
            view = self._capture(io)
            if view is not None and check(view[0]):
                return True
            self._sleep(self._wait_sec)
        return False

    def _draw_market(self, io: GameIo, move: DrawMarket, state: KahunaState) -> ExecutionResult:
        view = self._capture(io)
        if view is None:
            return ExecutionResult(False, "位置合わせの基準が見つからない")
        image, alignment = view
        if not self._is_my_turn(image, state):
            return ExecutionResult(False, "自分の手番の画面ではない")
        market, _ = read_market(image, self._templates)
        slots = [i for i, r in enumerate(market) if r is not None and r.island == move.card]
        if not slots:
            return ExecutionResult(False, f"場札に {self._board.islands[move.card]} が無い")
        slot = slots[0]
        x = MARKET_SLOT_X[slot] + MARKET_SLOT_W // 2
        self._tap(io, Point(x, MARKET_NAME_Y + MARKET_NAME_H // 2), alignment)
        after_view = self._capture(io)
        if after_view is None:
            return ExecutionResult(False, "場札の確認の画面で位置合わせできない")
        after = after_view[0]
        if classify_screen(after, self._templates).name != MY_TURN:
            return ExecutionResult(True)  # 引くと手番が終わり、手札が暗くなる
        current = read_market(after, self._templates)[0][slot]
        if current is not None and current.island == move.card:
            return ExecutionResult(False, "場札が引かれたことを確認できない")
        return ExecutionResult(True)
