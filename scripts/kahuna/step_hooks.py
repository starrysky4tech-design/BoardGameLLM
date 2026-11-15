"""Kahuna の step_once(scripts/common/step_once.py)への差し込み。

手札を使い切った手番は、画面から手番を区別できないので、引く操作が残っている印
(runs/kahuna/pending_draw)を置く。その印があるときだけ、相手の手番の表示でも盤面を読む。
認識は入力を送らない(決算ダイアログの CONTINUE も押さない)。
"""

from pathlib import Path
from typing import Any

from bglm.core.models import Recognition
from bglm.core.protocols import GameIo
from bglm.plugins.kahuna.logic.models import KahunaMove, KahunaState, PlaceStick
from bglm.plugins.kahuna.vision.recognizer import KahunaRecognizer
from bglm.plugins.kahuna.vision.screens import OPPONENT_TURN
from scripts.common.step_once import StepHooks

PENDING = Path("runs/kahuna/pending_draw")


def observe(plugin: Any, io: GameIo, from_start: bool) -> Recognition[KahunaState]:
    recognizer: KahunaRecognizer = plugin.recognizer()
    image = io.capture().image
    recognition = recognizer.recognize(image)
    if recognition.state is None and PENDING.exists() and recognition.ui.screen == OPPONENT_TURN:
        return recognizer.read_board_as_my_turn(image)
    return recognition


def after(state: KahunaState, move: KahunaMove) -> None:
    PENDING.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(move, PlaceStick) and len(state.hand) == 1:
        PENDING.write_text("hand-empty", encoding="utf-8")  # 最後の1枚を使った。引くまでが手番
    elif PENDING.exists():
        PENDING.unlink()  # 引く操作を終えた


HOOKS = StepHooks(observe=observe, after=after)
