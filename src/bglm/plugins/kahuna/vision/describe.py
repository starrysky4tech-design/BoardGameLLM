"""認識結果を、評価セットの正解と比べる要素ごとの値に分解する。"""

from typing import Any

from bglm.core.models import Recognition
from bglm.plugins.kahuna.logic.models import BoardDef, KahunaState, default_board

_OWNER = {None: "-", 0: "M", 1: "O"}  # 無し、自分(Me)、相手(Opponent)


def describe_recognition(
    recognition: Recognition[KahunaState], board: BoardDef | None = None
) -> dict[str, Any]:
    board = board or default_board()
    state = recognition.state
    if state is None:
        return {}
    result: dict[str, Any] = {
        "hand": sorted(board.islands[c] for c in state.hand),
        "market": [board.islands[c] for c in state.market],
        "deck": state.deck_count,
        "round": state.round,
        "score_me": state.scores[0],
        "score_opponent": state.scores[1],
    }
    for i, owner in enumerate(state.sticks):
        result[f"sticks[{i}]"] = _OWNER[owner]
    for i, owner in enumerate(state.stones):
        result[f"stones[{i}]"] = _OWNER[owner]
    return result
