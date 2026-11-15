"""Maquis の認識。1枚の取得画像から盤を読み、直前の状態と照らして状態を決める(docs/02「Recognizer」)。

読み方(board_reading.py): 地点の団員・巡回、「!」、資材、団員の数(N/M)、フェイズ、任務の★を画面から読む。
画面から読めないもの(ターン数、行動済み、山札の残り)は、直前の状態に、合法手を高々1〜2手打った結果として
照合し、一致した状態から引き継ぐ。一致しなければ入力を送らず止まる(推測で埋めない)。

- 山札: 巡回が1つ増えたら、山札の画面を開いて捨札の先頭を読み、山札から引く(deck_reader.py)。
  巡回がいくつ増えたか分からない(2つ以上)ときは、カードが決まらないので止まる
- 最初の観測(直前の状態が無い)は、対局の開始直後(団員を置く前、山札10枚)とみなして照合する。
  対局の途中から始めると一致せず止まる(山札が分からないため)
- 終局: 「レジスタンス壊滅」の画面は、敗北の状態を返す。それ以外の終局画面(勝ち・引き分けは未観測)は、
  勝敗を決めずに GAME_OVER とする
"""

from dataclasses import replace

import cv2
import numpy as np
from numpy.typing import NDArray

from bglm.core.models import Frame, Recognition, UiKind, UiState
from bglm.core.protocols import GameIo
from bglm.plugins.maquis.logic.board import Board, default_board
from bglm.plugins.maquis.logic.models import MaquisState
from bglm.plugins.maquis.logic.patrol import PatrolDeck, full_deck, landing
from bglm.plugins.maquis.logic.rules import MaquisRules, initial_state
from bglm.plugins.maquis.vision import layout
from bglm.plugins.maquis.vision.alignment import Alignment
from bglm.plugins.maquis.vision.board_reading import BoardReading, read_board
from bglm.plugins.maquis.vision.deck_reader import DeckReader
from bglm.plugins.maquis.vision.screens import ScreenKind, classify_screen

FOLLOW_PLIES = 2  # 直前の状態から観測の盤まで進める手数の上限
SETTLING = (
    "settling"  # 画面が落ち着くのを待つ(新しいターンの開始直後に、前のターンの巡回が残っている)
)


def _unknown(confidence: float, low: tuple[str, ...]) -> Recognition[MaquisState]:
    return Recognition(UiState(UiKind.UNKNOWN, "unknown"), None, confidence, low)


def _waiting(confidence: float, low: tuple[str, ...]) -> Recognition[MaquisState]:
    return Recognition(UiState(UiKind.WAITING, "settling"), None, confidence, low)


class MaquisRecognizer:
    def __init__(
        self,
        rules: MaquisRules | None = None,
        deck_reader: DeckReader | None = None,
        board: Board | None = None,
        alignment: Alignment | None = None,
        resume: MaquisState | None = None,
    ) -> None:
        self._resume = resume  # 直前の状態が無いときの出発点(対局の途中からの再開)
        self._alignment = alignment or Alignment()
        self._board = board or default_board()
        self._rules = rules or MaquisRules(self._board)
        self._deck_reader = deck_reader or DeckReader()

    def observe(self, io: GameIo, previous: MaquisState | None) -> Recognition[MaquisState]:
        aligned = self._alignment.wrap(io)  # 描画の横ずれを補正する(alignment.py)
        return self.recognize(aligned, aligned.capture().image, previous)

    def recognize(
        self, io: GameIo, image: NDArray[np.uint8], previous: MaquisState | None
    ) -> Recognition[MaquisState]:
        screen = classify_screen(image)
        if screen is ScreenKind.END_DEFEAT:
            base = previous if previous is not None else initial_state()
            return Recognition(
                UiState(UiKind.GAME_OVER, "end_defeat"), replace(base, defeated=True), 1.0
            )
        if screen is ScreenKind.END_OTHER:
            return Recognition(
                UiState(UiKind.GAME_OVER, "end_unknown"), None, 1.0, ("end_unknown",)
            )
        if screen is not ScreenKind.BOARD:
            return _unknown(0.0, (screen.value,))

        result = read_board(image, self._board)
        if result.reading is None:
            if result.fatal:
                return _unknown(result.confidence, result.problems)
            return _waiting(
                result.confidence, result.problems
            )  # 演出の途中かもしれない。待って読み直す
        reading = result.reading
        base = previous if previous is not None else self._start()
        found = self._follow(base, reading)
        if found is None:
            return _waiting(reading.confidence, ("no_matching_move",))
        candidate, plies = found
        state, problem = self._finish(io, base, candidate, reading, plies)
        if state is None:
            if problem == SETTLING:
                return _waiting(reading.confidence, (SETTLING,))
            return _unknown(reading.confidence, (problem or "state",))
        return Recognition(UiState(UiKind.PLAYABLE, "board"), state, reading.confidence)

    def _start(self) -> MaquisState:
        return self._resume if self._resume is not None else initial_state()

    # --- 前の状態との照合 ---

    def _follow(
        self, previous: MaquisState, reading: BoardReading
    ) -> tuple[MaquisState, int] | None:
        """直前の状態から 0〜2 手(自分の手)で、観測の盤になる状態と、打った手数。"""
        frontier = [previous]
        for plies in range(FOLLOW_PLIES + 1):
            for state in frontier:
                if _matches(state, reading):
                    return state, plies
            if plies == FOLLOW_PLIES:
                break
            frontier = [
                self._rules.apply(state, move)
                for state in frontier
                for move in self._rules.legal_moves(state)
            ]
        return None

    def _finish(
        self,
        io: GameIo,
        previous: MaquisState,
        candidate: MaquisState,
        reading: BoardReading,
        plies: int,
    ) -> tuple[MaquisState | None, str | None]:
        """照合した状態に、観測した巡回・資材・山札を入れる。"""
        if reading.prison != (candidate.prisoners > 0):
            return None, "prison_mismatch"
        deck = candidate.deck
        if candidate.turn != previous.turn:
            # 新しいターンの開始。巡回の絵がまだ消えていなければ、演出の途中(待って読み直す)
            if reading.patrols:
                return None, SETTLING
            new_patrols: frozenset[str] = frozenset()
        else:
            new_patrols = reading.patrols - previous.patrols
        if len(new_patrols) > 1:
            return None, "missed_draws"  # 2つ以上増えた。引かれたカードが決まらない
        if len(new_patrols) == 1:
            drawn, problem = self._draw(io, previous, candidate, next(iter(new_patrols)))
            if drawn is None:
                return None, problem
            deck = drawn
        state = replace(candidate, patrols=reading.patrols, resources=reading.resources, deck=deck)
        return state, None

    def _draw(
        self, io: GameIo, previous: MaquisState, candidate: MaquisState, appeared: str
    ) -> tuple[PatrolDeck | None, str | None]:
        read = self._deck_reader.read_discard_top(io)
        if read.problem is not None:
            return None, read.problem
        if read.card is None:
            return None, "no_discard_card"
        # 引かれたカードが、巡回の出た地点と矛盾しないか(団員と、既にいる巡回は飛ばされる)
        occupied = (
            frozenset(a for a in candidate.agents if a not in self._board.missions)
            | previous.patrols
        )
        if landing(read.card, occupied) != appeared:
            return None, "card_mismatch"
        try:
            return candidate.deck.drawn_from(read.card, full_deck()), None
        except ValueError:
            return None, "card_not_in_deck"

    # --- デバッグ ---

    def debug_overlay(self, frame: Frame, result: Recognition[MaquisState]) -> NDArray[np.uint8]:
        canvas = frame.image.copy()
        state = result.state
        if state is None:
            return np.asarray(canvas, dtype=np.uint8)
        for node, (x, y) in layout.NODE_CENTER.items():
            tag = "P" if node in state.patrols else "A" if node in state.agents else ""
            if tag:
                cv2.putText(
                    canvas, tag, (x - 10, y + 10), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0, 0, 255), 4
                )
        return np.asarray(canvas, dtype=np.uint8)


def _matches(state: MaquisState, reading: BoardReading) -> bool:
    """画面から読めた項目が、状態と一致するか。士気は演出(ターントラックのオレンジのターン)で変わる
    が、まだルールに入れていない(未確認)ので、比べない。"""
    a, b = state.resources, reading.resources
    same_resources = all(a.get(n) == b.get(n) for n in a.__dataclass_fields__ if n != "morale")
    return (
        state.phase is reading.phase
        and state.unplaced == reading.unplaced
        and state.agents_total == reading.agents_total
        and state.agents == reading.agents
        and state.stars == reading.stars
        and same_resources
    )
