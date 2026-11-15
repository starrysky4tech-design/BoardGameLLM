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
from bglm.toolkit.waiting import poll

TAP_WAIT_SEC = 1.0  # タップ後の画面が落ち着くまでの待ち
SETTLE_TRIES = 4  # 操作の結果を確かめる取得の回数(杖や捨て札の表示は少し遅れて出る)

# 録画の座標(位置合わせ後)。実機の2026-10-31の操作で確かめた位置。
DECK_TAP = Point(1066, 1045)  # 山札の中央(ALOA ステージで引けた位置)
END_TURN_TAP = Point(2339, 997)  # 右下の手のマーク
DISCARD_TAP = Point(805, 1007)  # 「DISCARD」の文字(カードを選ぶと出る)

View = tuple[NDArray[np.uint8], Alignment]


def _fail(reason: str) -> ExecutionResult:
    return ExecutionResult(False, reason)


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
                return _fail(f"未確認の操作: {type(move).__name__}")

    # --- 操作 -------------------------------------------------------------------

    def _place_stick(self, io: GameIo, move: PlaceStick) -> ExecutionResult:
        view = self._my_turn_view(io)
        if isinstance(view, ExecutionResult):
            return view
        image, alignment = view
        if not self._select_hand_card(io, read_hand(image, self._templates), move.card, alignment):
            return _fail(f"手札に {self._board.islands[move.card]} が無い")
        line = self._board.lines[move.line].position
        self._tap(io, line, alignment)
        if self._wait_until(io, lambda img: self._has_stick(img, line, Player.ME)):
            return ExecutionResult(True)
        return _fail("杖コマが置かれたことを確認できない")

    def _remove_stick(self, io: GameIo, move: RemoveStick) -> ExecutionResult:
        view = self._my_turn_view(io)
        if isinstance(view, ExecutionResult):
            return view
        image, alignment = view
        hand = read_hand(image, self._templates)
        first, second = move.cards
        if first == second or any(self._best_card(hand, c) is None for c in (first, second)):
            return _fail("除去に必要な2枚が手札に無い")
        self._select_hand_card(io, hand, first, alignment)
        self._select_hand_card(io, hand, second, alignment)
        line = self._board.lines[move.line].position
        self._tap(io, line, alignment)  # 2枚選ぶと出る赤い丸
        if self._capture(io) is None:
            return _fail("除去の確認の画面で位置合わせできない")
        if self._wait_until(io, lambda img: not self._has_stick(img, line, Player.OPPONENT)):
            return ExecutionResult(True)
        return _fail("相手の杖が取り除かれたことを確認できない")

    def _discard(self, io: GameIo, move: DiscardCard) -> ExecutionResult:
        view = self._my_turn_view(io)
        if isinstance(view, ExecutionResult):
            return view
        image, alignment = view
        hand = read_hand(image, self._templates)
        if not self._select_hand_card(io, hand, move.card, alignment):
            return _fail(f"手札に {self._board.islands[move.card]} が無い")
        self._tap(io, DISCARD_TAP, alignment)
        if self._capture(io) is None:
            return _fail("捨てた後の画面で位置合わせできない")
        if self._wait_until(io, lambda img: len(read_hand(img, self._templates)) == len(hand) - 1):
            return ExecutionResult(True)
        return _fail("手札が1枚減ったことを確認できない")

    def _draw_deck(self, io: GameIo, state: KahunaState) -> ExecutionResult:
        view = self._my_turn_view(io, state)
        if isinstance(view, ExecutionResult):
            return view
        image, alignment = view
        before = len(read_hand(image, self._templates))
        self._tap(io, DECK_TAP, alignment)
        if self._wait_until(io, lambda img: len(read_hand(img, self._templates)) == before + 1):
            return ExecutionResult(True)
        return _fail("山札から引けたことを確認できない")

    def _end_turn(self, io: GameIo, state: KahunaState) -> ExecutionResult:
        view = self._my_turn_view(io, state)
        if isinstance(view, ExecutionResult):
            return view
        self._tap(io, END_TURN_TAP, view[1])
        after_view = self._capture(io)
        if after_view is None:
            return ExecutionResult(True)  # 決算などで位置合わせできないのは、手番が変わった証拠
        if classify_screen(after_view[0], self._templates).name == MY_TURN:
            return _fail("手番が終わったことを確認できない")
        return ExecutionResult(True)

    def _draw_market(self, io: GameIo, move: DrawMarket, state: KahunaState) -> ExecutionResult:
        view = self._my_turn_view(io, state)
        if isinstance(view, ExecutionResult):
            return view
        image, alignment = view
        market, _ = read_market(image, self._templates)
        slots = [i for i, r in enumerate(market) if r is not None and r.island == move.card]
        if not slots:
            return _fail(f"場札に {self._board.islands[move.card]} が無い")
        slot = slots[0]
        x = MARKET_SLOT_X[slot] + MARKET_SLOT_W // 2
        self._tap(io, Point(x, MARKET_NAME_Y + MARKET_NAME_H // 2), alignment)
        after_view = self._capture(io)
        if after_view is None:
            return _fail("場札の確認の画面で位置合わせできない")
        after = after_view[0]
        if classify_screen(after, self._templates).name != MY_TURN:
            return ExecutionResult(True)  # 引くと手番が終わり、手札が暗くなる
        current = read_market(after, self._templates)[0][slot]
        if current is not None and current.island == move.card:
            return _fail("場札が引かれたことを確認できない")
        return ExecutionResult(True)

    # --- 共通の手順 -------------------------------------------------------------

    def _my_turn_view(self, io: GameIo, state: KahunaState | None = None) -> View | ExecutionResult:
        """操作の前提: 取得 → 位置合わせ → 自分の手番の確認。満たさなければ失敗の結果を返す(入力は送らない)。

        state を渡すと、手札が0枚の状態に限り、相手の手番の表示でも自分の手番とみなす(引く・終える操作)。
        手札が0枚の手番は、画面から区別できないため。
        """
        view = self._capture(io)
        if view is None:
            return _fail("位置合わせの基準が見つからない")
        name = classify_screen(view[0], self._templates).name
        hand_empty = state is not None and not state.hand
        if name != MY_TURN and not (hand_empty and name == OPPONENT_TURN):
            return _fail("自分の手番の画面ではない")
        return view

    @staticmethod
    def _best_card(hand: list[CardReading], island: int) -> CardReading | None:
        """手札の指定の島のカード。同じ島のカードが複数なら、確かに読めた方。"""
        matches = [c for c in hand if c.island == island]
        return max(matches, key=lambda c: c.score) if matches else None

    def _select_hand_card(
        self, io: GameIo, hand: list[CardReading], island: int, alignment: Alignment
    ) -> bool:
        """手札の指定の島のカードを、読み取った位置で押す。無ければ False(押さない)。"""
        card = self._best_card(hand, island)
        if card is None:
            return False
        self._tap(io, Point(card.x, card.y), alignment)
        return True

    @staticmethod
    def _has_stick(image: NDArray[np.uint8], at: Point, owner: Player) -> bool:
        """at の近くに、owner の杖コマがあるか。"""
        for blob in find_blobs(image):
            near = ((blob.center.x - at.x) ** 2 + (blob.center.y - at.y) ** 2) ** 0.5
            if blob.owner is owner and near <= MAX_DISTANCE:
                return True
        return False

    def _tap(self, io: GameIo, point: Point, alignment: Alignment) -> None:
        """録画の座標の点を、取得画像の座標に直して押す。"""
        io.perform(Tap(alignment.to_screen(point)))
        self._sleep(self._wait_sec)

    def _capture(self, io: GameIo) -> View | None:
        """録画の座標に揃えた画像と、ずれ。基準が見つからなければ None。"""
        return aligned_view(io.capture().image, self._templates.anchor)

    def _wait_until(
        self, io: GameIo, check: Callable[[NDArray[np.uint8]], bool], tries: int = SETTLE_TRIES
    ) -> bool:
        """画面が落ち着くまで、取り直しながら確かめる(杖や捨て札の表示は少し遅れて出る)。"""
        _, ok = poll(
            lambda: self._capture(io),
            lambda view: view is not None and check(view[0]),
            tries=tries,
            wait_sec=self._wait_sec,
            sleep=self._sleep,
            wait_last=True,
        )
        return ok
