"""手番の終わりとラウンドの終わり(出典: ルールブック R p.5、p.9、p.11)。

手番の終わり: トレイの補充 → 次のプレイヤーへ(キューブが残る人だけ)。
ラウンドの終わり: 目的の採点 → トレイを入れ替え → 先手を左隣へ → キューブを配り直す。
"""

from dataclasses import replace

from bglm.plugins.wingspan.logic.board import TRAY_SIZE, TURNS_PER_ROUND
from bglm.plugins.wingspan.logic.cards import CardTable
from bglm.plugins.wingspan.logic.goals import goal_points
from bglm.plugins.wingspan.logic.helpers import pop_deck
from bglm.plugins.wingspan.logic.state import WingspanState


def refill_tray(state: WingspanState) -> WingspanState:
    """空いた枠を山札から補充する。補充は手番の終わりに行う(R p.9)。"""
    tray = list(state.tray)
    for i, card in enumerate(tray):
        if card == "":
            state, taken = pop_deck(state, 1)
            tray[i] = taken[0] if taken else ""
    return replace(state, tray=tuple(tray))


def end_round(state: WingspanState, table: CardTable) -> WingspanState:
    boards = state.players
    tile = state.goals[state.round_index]
    points = goal_points(
        tile, boards, state.round_index, state.goal_mode, lambda n: table.bird(n).nest
    )
    for i, pts in enumerate(points):
        board = state.players[i]
        state = state.with_player(i, replace(board, goal_points=board.goal_points + (pts,)))
    # トレイの表向きの札をすべて捨てて入れ替える(R p.5)
    discarded = tuple(c for c in state.tray if c)
    state = replace(state, discard=state.discard + discarded, tray=("",) * TRAY_SIZE)
    state = refill_tray(state)
    next_round = state.round_index + 1
    state = replace(
        state,
        round_index=next_round,
        first_player=(state.first_player + 1) % len(state.players),
    )
    if next_round < len(TURNS_PER_ROUND):
        for i, board in enumerate(state.players):
            state = state.with_player(i, replace(board, cubes=TURNS_PER_ROUND[next_round]))
        state = replace(state, to_move=state.first_player)
    return state


def _clear_used(state: WingspanState, player: int) -> WingspanState:
    """桃色の能力の「使い済み」は、その持ち主の次の手番の始めに戻る(R p.10)。"""
    from bglm.plugins.wingspan.logic.models import PlacedBird

    board = state.players[player]
    for at in board.placements():
        bird = board.bird_at(at)
        if bird.used:
            board = board.with_bird(
                at, PlacedBird(bird.name, bird.eggs, bird.cached, bird.tucked, used=False)
            )
    return state.with_player(player, board)


def end_turn(state: WingspanState, table: CardTable) -> WingspanState:
    """行動が済んだ後の処理。次に動く人、またはラウンドの切り替わりまで進める。"""
    state = refill_tray(state)
    if all(b.cubes == 0 for b in state.players):
        return end_round(state, table)
    count = len(state.players)
    for step in range(1, count + 1):
        candidate = (state.to_move + step) % count
        if state.players[candidate].cubes > 0:
            state = replace(state, to_move=candidate)
            return _clear_used(state, candidate)
    return state
