"""Maquis の手を、タップに変えて実行する(docs/02 の「MoveExecutor」)。

- `Place`: 地点(または任務の枠)をタップ → 右列の1枠目(`PLACE_BTN`)をタップ。確認ダイアログは出ない
- `Resolve`: 地点をタップ → 右列の `SLOT_Y[slot]` をタップ
- `EndPhase`: 終了ボタン(`END_BTN`)を **1回だけ** 押す → 画面を確かめ、確認ダイアログのときだけ、確定をもう1回押す。
  終了ボタンと確定ボタンは同じ位置なので、無条件に2回押すと次のフェイズの終了まで押してしまう(実機で壊滅した)

安全: 押す前に必ず盤の画面(`ScreenKind.BOARD`)であることを確かめる。「完全版を入手」や宣伝の領域は押さない。
実行の後は認識器で読み直し、予測した状態と一致したときだけ成功とする。一致しなければ止まる(推測で進めない)。
"""

import time
from collections.abc import Callable
from dataclasses import replace

from bglm.core.models import ExecutionResult, InputAction, Point, Tap
from bglm.core.protocols import GameIo
from bglm.plugins.maquis.logic.board import Board, default_board
from bglm.plugins.maquis.logic.models import EndPhase, MaquisMove, MaquisState, Place, Resolve
from bglm.plugins.maquis.logic.rules import MaquisRules
from bglm.plugins.maquis.vision import layout
from bglm.plugins.maquis.vision.alignment import Alignment
from bglm.plugins.maquis.vision.recognizer import MaquisRecognizer
from bglm.plugins.maquis.vision.screens import ScreenKind, classify_screen
from bglm.toolkit.waiting import poll

SELECT_WAIT_SEC = 0.8  # 地点を選んだ後、右列にボタンが出るまでの待ち
SETTLE_SEC = 3.8  # 確定のタップの後(配置の演出は約2.5秒)
CONFIRM_WAIT_SEC = 1.0  # 終了ボタンを押した後、確認ダイアログが出るまでの待ち
END_SCREEN_TRIES = 6  # 帯(演出)が消えて、盤か確認ダイアログと判別できるまで取り直す回数
VERIFY_TRIES = 14  # ターン切り替えの演出(士気の低下など)は長い。約20秒まで待つ
VERIFY_WAIT_SEC = 1.5
END_TURN_SETTLE_SEC = 5.0  # ターン終了後、巡回の演出が収まるまでの待ち


class MaquisExecutor:
    def __init__(
        self,
        rules: MaquisRules | None = None,
        recognizer: MaquisRecognizer | None = None,
        board: Board | None = None,
        alignment: Alignment | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._alignment = alignment or Alignment()
        self._board = board or default_board()
        self._rules = rules or MaquisRules(self._board)
        self._recognizer = recognizer or MaquisRecognizer(
            self._rules, board=self._board, alignment=self._alignment
        )
        self._sleep = sleep

    def execute(self, io: GameIo, state: MaquisState, move: MaquisMove) -> ExecutionResult:
        io = self._alignment.wrap(io)  # 描画の横ずれを補正する(alignment.py)
        if classify_screen(io.capture().image) is not ScreenKind.BOARD:
            return ExecutionResult(False, "not_board")
        actions: list[InputAction] = []
        if isinstance(move, EndPhase):
            problem = self._end_phase(io, actions)
        else:
            problem = self._select_and_press(io, state, move, actions)
        if problem is not None:
            return ExecutionResult(False, problem, tuple(actions))
        return self._verify(io, state, move, tuple(actions))

    # --- タップ ---

    def _tap(self, io: GameIo, at: tuple[int, int], actions: list[InputAction]) -> None:
        action = Tap(Point(*at))
        io.perform(action)
        actions.append(action)

    def _target(self, location: str) -> tuple[int, int] | None:
        if location in self._board.missions:
            return layout.MISSION_BUTTON[location]
        return layout.NODE_CENTER.get(location)

    def _select_and_press(
        self, io: GameIo, state: MaquisState, move: Place | Resolve, actions: list[InputAction]
    ) -> str | None:
        target = self._target(move.location)
        if target is None:
            return f"unknown_location:{move.location}"
        if isinstance(move, Place):
            button = layout.PLACE_BTN
        elif 0 <= move.slot < len(layout.SLOT_Y):
            button = (layout.PLACE_BTN[0], layout.SLOT_Y[move.slot])
        else:
            return f"bad_slot:{move.slot}"
        self._tap(io, target, actions)
        self._sleep(SELECT_WAIT_SEC)
        # 選んだ後も盤の画面のまま(想定外のダイアログが出ていない)ことを確かめてから、右列を押す
        if classify_screen(io.capture().image) is not ScreenKind.BOARD:
            return "not_board_after_select"
        self._tap(io, button, actions)
        self._sleep(SETTLE_SEC)
        return None

    def _end_phase(self, io: GameIo, actions: list[InputAction]) -> str | None:
        self._tap(io, layout.END_BTN, actions)
        # 押した直後は、「ターン○ - 行動フェイズ」の帯が画面を暗くかぶせて、盤と判別できない(実機で確認)。
        # 帯が消えるまで待って取り直し、確認ダイアログのときだけ確定を押す
        screen, ok = poll(
            lambda: classify_screen(io.capture().image),
            lambda kind: kind is not ScreenKind.UNKNOWN,
            tries=END_SCREEN_TRIES,
            wait_sec=CONFIRM_WAIT_SEC,
            sleep=self._sleep,
            wait_first=True,
        )
        if not ok:
            return "unexpected_screen:unknown"
        if screen is ScreenKind.CONFIRM:
            self._tap(io, layout.END_BTN, actions)  # 確定。押すのはここで1回だけ
        elif screen not in (ScreenKind.BOARD, ScreenKind.END_DEFEAT, ScreenKind.END_OTHER):
            return f"unexpected_screen:{screen.value}"
        self._sleep(END_TURN_SETTLE_SEC)
        return None

    # --- 結果の確認 ---

    def _verify(
        self,
        io: GameIo,
        state: MaquisState,
        move: MaquisMove,
        actions: tuple[InputAction, ...],
    ) -> ExecutionResult:
        expected = self._rules.apply(state, move)

        def probe() -> tuple[ScreenKind, MaquisState | None]:
            image = io.capture().image
            screen = classify_screen(image)
            if screen is not ScreenKind.BOARD:
                return screen, None
            return screen, self._recognizer.recognize(io, image, state).state

        def accepted(seen: tuple[ScreenKind, MaquisState | None]) -> bool:
            screen, actual = seen
            if screen in (ScreenKind.END_DEFEAT, ScreenKind.END_OTHER):
                return isinstance(move, EndPhase)  # 終了で終局になった。それ以外の手では起きない
            if actual is None:
                return False
            # 士気は、ターントラックのオレンジのターンで下がる(ルール未実装)ので、認識器と同じく比べない
            same_morale = replace(
                expected, resources=replace(expected.resources, morale=actual.resources.morale)
            )
            return not self._rules.diff(same_morale, actual)

        seen, ok = poll(
            probe,
            accepted,
            tries=VERIFY_TRIES,
            wait_sec=VERIFY_WAIT_SEC,
            sleep=self._sleep,
        )
        if ok:
            return ExecutionResult(True, actions=actions)
        reason = "verify_failed"
        if seen[0] is not ScreenKind.BOARD:
            reason = f"verify_failed:{seen[0].value}"
        return ExecutionResult(False, reason, actions)
