"""Kahuna の認識。1枚の取得画像から、画面の種類と盤面の全要素を読む。

決算ダイアログ(CONTINUE)は、ゲームの手ではなく進行の確認なので、ここで押して待ちを返す。
ゲーム終了のダイアログ(NEXT)は押さず、勝敗だけ読んで GAME_OVER を返す(押すかは人が決める)。
"""

import time
from collections.abc import Callable

import cv2
import numpy as np
from numpy.typing import NDArray

from bglm.core.models import Frame, Point, Recognition, Tap, UiKind, UiState
from bglm.core.protocols import GameIo
from bglm.plugins.kahuna.logic.models import (
    BoardDef,
    KahunaState,
    Player,
    default_board,
)
from bglm.plugins.kahuna.vision import screens
from bglm.plugins.kahuna.vision.alignment import aligned_view
from bglm.plugins.kahuna.vision.cards import MARKET_SLOT_X, read_hand, read_market
from bglm.plugins.kahuna.vision.numbers import read_deck, read_round, read_score
from bglm.plugins.kahuna.vision.sticks import assign_to_lines, find_blobs
from bglm.plugins.kahuna.vision.stones import find_stones
from bglm.plugins.kahuna.vision.templates import TemplateSet

CONTINUE_BUTTON = Point(1255, 850)  # 決算ダイアログのボタン(NEXT も同じ位置)
ELEMENT_MIN = 0.70  # 要素の信頼度がこれ未満なら low_confidence に入れる
HAND_MAX = 5
WINNER_ROI = (640, 780, 1000, 1520)  # y0, y1, x0, x1
WINNER_MIN_SCORE = 0.80
RETRIES = 2  # 読めなかったときの取り直しの回数
RETRY_WAIT_SEC = 1.0


class KahunaRecognizer:
    def __init__(
        self,
        templates: TemplateSet | None = None,
        board: BoardDef | None = None,
        *,
        retries: int = RETRIES,
        retry_wait_sec: float = RETRY_WAIT_SEC,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._board = board or default_board()
        self._templates = templates or TemplateSet.load(board=self._board)
        self._retries = retries
        self._retry_wait_sec = retry_wait_sec
        self._sleep = sleep

    def observe(self, io: GameIo, previous: KahunaState | None) -> Recognition[KahunaState]:
        """自分の手番で読めなかったときは、カードの動き(配る・引く)が収まるのを待って取り直す。"""
        recognition = self.recognize(io.capture().image, io)
        for _ in range(self._retries):
            if recognition.ui.kind is not UiKind.PLAYABLE or recognition.state is not None:
                break
            self._sleep(self._retry_wait_sec)
            recognition = self.recognize(io.capture().image, io)
        return recognition

    def recognize(
        self, image: NDArray[np.uint8], io: GameIo | None = None
    ) -> Recognition[KahunaState]:
        """画像から認識する。io があるときだけ、決算ダイアログを進める。

        表示が録画から横にずれていても読めるよう、まず録画の座標へ揃える。基準が見つからなければ
        UNKNOWN にして止める(ずれたままの座標で操作しないため)。
        """
        view = aligned_view(image, self._templates.anchor)
        if view is None:
            return self._unaligned(image)
        image, alignment = view
        screen = screens.classify_screen(image, self._templates)
        ui = UiState(screen.kind, screen.name)
        if screen.name == screens.ROUND_END and io is not None:
            io.perform(Tap(alignment.to_screen(CONTINUE_BUTTON)))
        if screen.name == screens.GAME_END:
            return self._game_over(image, ui, screen.confidence)
        if screen.kind is not UiKind.PLAYABLE:
            return Recognition(ui, None, screen.confidence)
        return self._read_board(image, ui)

    def read_board_as_my_turn(self, image: NDArray[np.uint8]) -> Recognition[KahunaState]:
        """手札が0枚のとき、画面から手番を区別できない。呼び出し側が自分の手番だと知っている場合に、盤面だけ読む。

        手札を使い切った手番は、必ず引く操作で終わるので、その時だけ使う。
        """
        view = aligned_view(image, self._templates.anchor)
        if view is None:
            return Recognition(UiState(UiKind.UNKNOWN, "unaligned"), None, 0.0)
        return self._read_board(view[0], UiState(UiKind.PLAYABLE, screens.MY_TURN))

    def _unaligned(self, image: NDArray[np.uint8]) -> Recognition[KahunaState]:
        """基準が見つからない画像。タップも盤面の読み取りもしない画面だけ、画面名を返す。

        タイトル・ステージ選択・読み込み中などは、位置を使わないので判別できる。手番や決算は
        位置を使って操作・読み取りするため、ずれたまま扱わず UNKNOWN で止める。
        """
        screen = screens.classify_screen(image, self._templates)
        if screen.kind is UiKind.UNKNOWN or screen.name in (screens.LOADING, screens.BANNER):
            return Recognition(UiState(screen.kind, screen.name), None, screen.confidence)
        return Recognition(UiState(UiKind.UNKNOWN, "unaligned"), None, 0.0)

    def _read_board(self, image: NDArray[np.uint8], ui: UiState) -> Recognition[KahunaState]:
        board, templates = self._board, self._templates
        confidences: dict[str, float] = {}

        blobs = find_blobs(image)
        sticks, unassigned = assign_to_lines(board, blobs)
        confidences["sticks"] = 0.0 if unassigned else 1.0

        stones, stone_scores = find_stones(image, board, templates)
        found = [s for s in stone_scores if s > 0]
        confidences["stones"] = min(found) if found else 1.0

        hand = read_hand(image, templates)
        confidences["hand"] = min((c.score for c in hand), default=1.0)
        if len(hand) > HAND_MAX:
            confidences["hand"] = 0.0

        market, market_confidence = read_market(image, templates)
        confidences["market"] = market_confidence

        readings = {
            "deck": read_deck(image, templates),
            "round": read_round(image, templates),
            "score_me": read_score(image, templates, mine=True),
            "score_opponent": read_score(image, templates, mine=False),
        }
        for name, reading in readings.items():
            confidences[name] = reading.confidence if reading.value else 0.0

        low = tuple(name for name, value in confidences.items() if value < ELEMENT_MIN)
        confidence = min(confidences.values())
        if low:
            return Recognition(ui, None, confidence, low)
        state = KahunaState(
            sticks=tuple(sticks),
            stones=tuple(stones),
            hand=tuple(c.island for c in hand),
            market=tuple(r.island for r in market if r is not None),
            deck_count=int(readings["deck"].value),
            round=int(readings["round"].value),
            scores=(int(readings["score_me"].value), int(readings["score_opponent"].value)),
        )
        return Recognition(ui, state, confidence)

    def _game_over(
        self, image: NDArray[np.uint8], ui: UiState, confidence: float
    ) -> Recognition[KahunaState]:
        """勝者の表示から勝敗を読む。読めなければ state=None(結果は記録されない)。"""
        y0, y1, x0, x1 = WINNER_ROI
        gray = np.asarray(cv2.cvtColor(image[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY), dtype=np.uint8)
        score = {
            name: float(
                cv2.matchTemplate(gray, self._templates.dialogs[name], cv2.TM_CCOEFF_NORMED).max()
            )
            for name in ("winner_me", "winner_draw")
        }
        if score["winner_me"] >= WINNER_MIN_SCORE:
            winner: Player | None = Player.ME
        elif score["winner_draw"] >= WINNER_MIN_SCORE:
            winner = None
        else:
            # 相手の名前は表示ごとに違い得るので、読めないときは結果を決めない
            return Recognition(ui, None, confidence, ("winner",))
        state = KahunaState(
            sticks=tuple([None] * len(self._board.lines)),
            stones=tuple([None] * len(self._board.islands)),
            hand=(),
            market=(),
            deck_count=0,
            round=3,
            scores=(0, 0),
            over=True,
            winner=winner,
        )
        return Recognition(ui, state, min(confidence, max(score.values())))

    def debug_overlay(self, frame: Frame, result: Recognition[KahunaState]) -> NDArray[np.uint8]:
        """認識した杖コマの持ち主と、手札・場札の位置を画像に重ねる。"""
        view = aligned_view(frame.image, self._templates.anchor)
        image = frame.image.copy() if view is None else view[0].copy()
        cv2.putText(
            image,
            f"{result.ui.screen} {result.confidence:.2f} low={list(result.low_confidence)}",
            (80, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (0, 255, 255),
            2,
        )
        state = result.state
        if state is None:
            return image
        for line, owner in zip(self._board.lines, state.sticks, strict=True):
            if owner is not None:
                colour = (255, 255, 255) if owner is Player.ME else (0, 0, 255)
                cv2.circle(image, (line.position.x, line.position.y), 14, colour, 3)
        for position, owner in zip(self._board.stone_positions, state.stones, strict=True):
            if owner is not None:
                colour = (0, 255, 0) if owner is Player.ME else (0, 128, 255)
                cv2.circle(image, (position.x, position.y), 24, colour, 3)
        for slot, island in zip(MARKET_SLOT_X, state.market, strict=False):
            cv2.putText(
                image,
                self._board.islands[island],
                (slot + 10, 1000),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.9,
                (0, 255, 255),
                2,
            )
        return image
