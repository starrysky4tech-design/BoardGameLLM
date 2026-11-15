"""手番の進行: 行動を選ぶ → 餌・卵・札を選ぶ → 鳥の能力を 1 羽ずつ使うか決める(アプリと同じ順)。

`legal_moves` は、状態の `queue` の先頭(いま答える決定)に対する手を返す。
`apply` は手を適用した後、決定の要らない場面を自動で進める(`settle`)。
"""

from dataclasses import replace
from itertools import combinations, combinations_with_replacement

from bglm.plugins.wingspan.logic import powers
from bglm.plugins.wingspan.logic.board import HABITAT_ACTION, action_strength, egg_cost
from bglm.plugins.wingspan.logic.cards import CardTable
from bglm.plugins.wingspan.logic.helpers import (
    add_to_bird,
    discard_card,
    draw_from_deck,
    eggable,
    gain_food,
    remove_card,
    roll_feeder,
    take_die,
)
from bglm.plugins.wingspan.logic.models import (
    FOODS,
    INV_OR_SEED,
    Action,
    Food,
    Habitat,
    PlacedBird,
    Placement,
    Timing,
)
from bglm.plugins.wingspan.logic.payment import minimal_payments
from bglm.plugins.wingspan.logic.rounds import end_turn
from bglm.plugins.wingspan.logic.state import (
    AckConfirm,
    AckMatView,
    AckRound,
    AckSkip,
    AckTurnStart,
    ConvertCard,
    ConvertFoodTask,
    Decline,
    DrawBonusTask,
    DrawCards,
    DrawTask,
    EggBonusTask,
    GainFood,
    GainFoodTask,
    KeepSetup,
    LayEgg,
    LayEggs,
    LayEggsTask,
    Move,
    PayEggForCard,
    PayFoodForEgg,
    PlayBird,
    PowersTask,
    Reroll,
    SetupTask,
    SkipPower,
    TakeDeck,
    TakeDie,
    TakeTray,
    Task,
    TuckCard,
    TuckTask,
    UsePower,
    WingspanState,
)


def _distinct(cards: tuple[str, ...]) -> list[str]:
    return list(dict.fromkeys(cards))


# ---- 合法手 ----


def _egg_sources(state: WingspanState, player: int, cost: int) -> list[tuple[Placement, ...]]:
    """鳥をプレイするときに払う卵の取り方(どの鳥から何個か)。"""
    if cost == 0:
        return [()]
    board = state.players[player]
    have = [p for p in board.placements() if board.bird_at(p).eggs > 0]
    options: list[tuple[Placement, ...]] = []
    for combo in combinations_with_replacement(have, cost):
        if all(combo.count(p) <= board.bird_at(p).eggs for p in set(combo)):
            options.append(combo)
    return options


def play_moves(state: WingspanState, table: CardTable) -> list[Move]:
    player = state.to_move
    board = state.players[player]
    moves: list[Move] = []
    for name in _distinct(board.hand):
        if not table.known(name):
            continue  # 読めない・表に無い札は置かない(推測しない)
        card = table.bird(name)
        for habitat in sorted(card.habitats, key=lambda h: h.value):
            cost = egg_cost(len(board.row(habitat)))
            if cost is None:
                continue
            for spend in minimal_payments(board.food, card.cost):
                for eggs in _egg_sources(state, player, cost):
                    moves.append(PlayBird(name, habitat, spend, eggs))
    return moves


def _setup_moves(state: WingspanState) -> list[Move]:
    board = state.players[state.to_move]
    moves: list[Move] = []
    seen: set[tuple[tuple[str, ...], tuple[Food, ...], str]] = set()
    for k in range(len(board.hand) + 1):
        for idx in combinations(range(len(board.hand)), k):
            birds = tuple(sorted(board.hand[i] for i in idx))
            for foods in combinations(FOODS, 5 - k):
                for bonus in _distinct(board.bonus):
                    key = (birds, foods, bonus)
                    if key not in seen:
                        seen.add(key)
                        moves.append(KeepSetup(birds, foods, bonus))
    return moves


_ACK_MOVES: dict[str, Move] = {
    "turn_start": AckTurnStart(),
    "confirm": AckConfirm(),
    "skip": AckSkip(),
    "round": AckRound(),
    "mat_view": AckMatView(),
}


def legal_moves(state: WingspanState, table: CardTable) -> list[Move]:
    if state.ack:
        return [
            _ACK_MOVES[state.ack]
        ]  # 最後のラウンドの採点の確認は、終局の状態でも出す(確認を閉じると終局の画面に進む)
    if state.terminal:
        return []
    player = state.to_move
    board = state.players[player]
    if not state.queue:
        return [GainFood(), LayEggs(), DrawCards(), *play_moves(state, table)]
    task = state.queue[0]
    match task:
        case SetupTask():
            return _setup_moves(state)
        case GainFoodTask():
            return _die_moves(state)
        case ConvertFoodTask():
            return [*(ConvertCard(c) for c in _distinct(board.hand)), Decline()]
        case LayEggsTask(where=where):
            spots = eggable(state, table, player)
            return [LayEgg(p) for p in spots if where is None or p == where]
        case EggBonusTask():
            return [*(PayFoodForEgg(f) for f in FOODS if board.count(f) > 0), Decline()]
        case DrawTask():
            moves: list[Move] = []
            seen: set[str] = set()
            for i, card in enumerate(state.tray):
                if card and card not in seen:
                    seen.add(card)
                    moves.append(TakeTray(i))
            if state.deck or state.discard:
                moves.append(TakeDeck())
            return moves
        case DrawBonusTask():
            spots = [p for p in board.placements() if board.bird_at(p).eggs > 0]
            return [*(PayEggForCard(p) for p in spots), Decline()]
        case PowersTask():
            return [UsePower(), SkipPower()]
        case TuckTask():
            return [*(TuckCard(c) for c in _distinct(board.hand)), SkipPower()]
    raise AssertionError(f"未知の決定: {task}")


def _die_moves(state: WingspanState) -> list[Move]:
    moves: list[Move] = []
    seen: set[str] = set()
    for i, face in enumerate(state.feeder):
        if face in seen:
            continue
        seen.add(face)
        if face == INV_OR_SEED:
            moves += [TakeDie(i, Food.INVERTEBRATE), TakeDie(i, Food.SEED)]
        else:
            moves.append(TakeDie(i, Food(face)))
    if len(set(state.feeder)) == 1:  # 残りがすべて同じ目なら、先に振り直してよい(R p.7)
        moves.append(Reroll())
    return moves


# ---- 適用 ----


def _push(state: WingspanState, *tasks: Task) -> WingspanState:
    return replace(state, queue=tasks + state.queue)


def _pop(state: WingspanState, *tasks: Task) -> WingspanState:
    return replace(state, queue=tasks + state.queue[1:])


def _use_cube(state: WingspanState) -> WingspanState:
    board = state.players[state.to_move]
    return state.with_player(state.to_move, replace(board, cubes=board.cubes - 1))


def _start_action(state: WingspanState, habitat: Habitat) -> WingspanState:
    """行動(餌・産卵・札を引く)を始める。キューブを置き、その行の強さの分の決定を積む。"""
    player = state.to_move
    state = _use_cube(state)
    row_size = len(state.players[player].row(habitat))
    n, convert = action_strength(habitat, row_size)
    powers_task = PowersTask(habitat, row_size - 1)
    action = HABITAT_ACTION[habitat]
    if action is Action.GAIN_FOOD:
        return replace(state, queue=(GainFoodTask(n, convert), powers_task))
    if action is Action.LAY_EGGS:
        return replace(state, queue=(LayEggsTask(n, convert), powers_task))
    return replace(state, queue=(DrawTask(n, convert), powers_task))


def _play_bird(state: WingspanState, table: CardTable, move: PlayBird) -> WingspanState:
    player = state.to_move
    card = table.bird(move.card)
    state = _use_cube(state)
    board = state.players[player]
    board = replace(board, hand=remove_card(board.hand, move.card))
    for food, n in zip(FOODS, move.spend, strict=True):
        board = board.with_food(food, -n)
    state = state.with_player(player, board)
    for at in move.egg_from:  # 卵はどの鳥から払ってもよい(R p.6)
        state = add_to_bird(state, player, at, eggs=-1)
    board = state.players[player]
    row = board.row(move.habitat) + (PlacedBird(move.card),)
    state = state.with_player(player, board.with_row(move.habitat, row))
    state = powers.trigger_pink(
        state, table, player, kind="on_opponent_play_habitat_gain_supply", habitat=move.habitat
    )
    if card.power.timing is Timing.WHEN_PLAYED:
        return replace(state, queue=(PowersTask(move.habitat, len(row) - 1, played=True),))
    return replace(state, queue=())


def _keep_setup(state: WingspanState, move: KeepSetup) -> WingspanState:
    player = state.to_move
    board = state.players[player]
    dropped = list(board.hand)
    for name in move.birds:
        dropped.remove(name)
    board = replace(
        board,
        hand=tuple(move.birds),
        food=tuple(1 if f in move.foods else 0 for f in FOODS),  # type: ignore[arg-type]
        bonus=(move.bonus,),
    )
    state = state.with_player(player, board)
    state = replace(state, discard=state.discard + tuple(dropped))
    pending = tuple(p for p in state.pending_setup if p != player)
    state = replace(state, pending_setup=pending)
    if pending:
        return replace(state, to_move=pending[0], queue=(SetupTask(),))
    return replace(state, to_move=state.first_player, queue=())


def apply_move(state: WingspanState, table: CardTable, move: Move) -> WingspanState:
    if isinstance(move, AckTurnStart | AckConfirm | AckSkip | AckRound | AckMatView):
        return replace(
            state, ack=""
        )  # 確認の画面を閉じるだけ。盤は変わらない(次の観測で画面から読む)
    player = state.to_move
    board = state.players[player]
    task = state.queue[0] if state.queue else None
    match move:
        case GainFood():
            state = _start_action(state, Habitat.FOREST)
        case LayEggs():
            state = _start_action(state, Habitat.GRASSLAND)
            state = powers.trigger_pink(
                state, table, player, kind="on_opponent_lay_eggs_lay_on_nest"
            )
        case DrawCards():
            state = _start_action(state, Habitat.WETLAND)
        case PlayBird():
            state = _play_bird(state, table, move)
        case KeepSetup():
            state = _keep_setup(state, move)
        case TakeDie(index=i, food=food) if isinstance(task, GainFoodTask):
            state = gain_food(take_die(state, i), player, food)
            state = _pop(state, replace(task, remaining=task.remaining - 1))
        case Reroll():
            state = roll_feeder(state)
        case ConvertCard(card=card):
            state = discard_card(state, player, card)
            state = _pop(state, GainFoodTask(1))
        case LayEgg(at=at) if isinstance(task, LayEggsTask):
            state = add_to_bird(state, player, at, eggs=1)
            state = _pop(state, replace(task, remaining=task.remaining - 1))
        case PayFoodForEgg(food=food):
            state = gain_food(state, player, food, -1)
            state = _pop(state, LayEggsTask(1))
        case TakeTray(index=i) if isinstance(task, DrawTask):
            card = state.tray[i]
            tray = state.tray[:i] + ("",) + state.tray[i + 1 :]
            state = replace(state, tray=tray)
            state = state.with_player(player, replace(board, hand=board.hand + (card,)))
            state = _pop(state, replace(task, remaining=task.remaining - 1))
        case TakeDeck() if isinstance(task, DrawTask):
            state = draw_from_deck(state, player, 1)
            state = _pop(state, replace(task, remaining=task.remaining - 1))
        case PayEggForCard(at=at):
            state = add_to_bird(state, player, at, eggs=-1)
            state = _pop(state, DrawTask(1))
        case Decline():
            state = _pop(state)
        case UsePower() | SkipPower() if isinstance(task, PowersTask):
            state = _resolve_power(state, table, task, use=isinstance(move, UsePower))
        case SkipPower() if isinstance(task, TuckTask):
            state = _pop(state)
        case TuckCard(card=card) if isinstance(task, TuckTask):
            state = _tuck(state, task, card)
        case _:
            raise ValueError(f"この決定では使えない手: {move} / {task}")
    finish_turn = not (isinstance(move, KeepSetup) and not state.pending_setup)
    return settle(state, table, finish_turn=finish_turn)


def _resolve_power(
    state: WingspanState, table: CardTable, task: PowersTask, *, use: bool
) -> WingspanState:
    player = state.to_move
    at = Placement(task.habitat, task.next_index)
    power = table.bird(state.players[player].bird_at(at).name).power
    after: tuple[Task, ...] = (
        () if task.played else (PowersTask(task.habitat, task.next_index - 1),)
    )
    extra: tuple[Task, ...] = ()
    if use and power.kind in powers.DECIDE:
        state, extra = powers.DECIDE[power.kind][1](state, table, player, at, power)
    return replace(state, queue=extra + after + state.queue[1:])


def _tuck(state: WingspanState, task: TuckTask, card: str) -> WingspanState:
    player = state.to_move
    board = state.players[player]
    state = state.with_player(player, replace(board, hand=remove_card(board.hand, card)))
    state = add_to_bird(state, player, task.at, tucked=1)
    if task.then_food is not None:
        state = gain_food(state, player, task.then_food)
    if task.then_lay:
        state = replace(state, queue=state.queue[1:])
        return _push(state, LayEggsTask(task.then_lay, where=task.at))
    return _pop(state)


# ---- 決定の要らない場面を進める ----


def settle(state: WingspanState, table: CardTable, *, finish_turn: bool = True) -> WingspanState:
    """決定が要らない場面(取れる物が無い、使える能力が無い、手番の終わり)を自動で進める。

    決定の列が空になったら手番の終わり。ただし初期選択が終わった直後は、最初の行動を待つ(finish_turn=False)。
    """
    while True:
        if state.terminal:
            return state
        if not state.queue:
            return end_turn(state, table) if finish_turn else state
        step = _settle_step(state, table)
        if step is None:
            return state
        state = step


def _settle_step(state: WingspanState, table: CardTable) -> WingspanState | None:
    """先頭の決定が自動で片付くなら新しい状態、人(思考)の答えが要るなら None。"""
    player = state.to_move
    board = state.players[player]
    task = state.queue[0]
    match task:
        case SetupTask():
            return None
        case GainFoodTask(remaining=0, convert=convert):
            return _pop(state, *((ConvertFoodTask(),) if convert and board.hand else ()))
        case GainFoodTask():
            return None  # 餌箱から取る決定(餌箱は空にならない。空になれば振り直される)
        case ConvertFoodTask():
            return None if board.hand else _pop(state)
        case LayEggsTask(remaining=n, bonus=bonus, where=where):
            spots = eggable(state, table, player)
            spots = [p for p in spots if where is None or p == where]
            if n == 0 or not spots:
                can_bonus = (
                    n == 0 and bonus and sum(board.food) > 0 and eggable(state, table, player)
                )
                return _pop(state, *((EggBonusTask(),) if can_bonus else ()))
            if where is not None:
                # 「この鳥の上に置く」産卵は置き先が 1 つに決まるので、決定を挟まず置く
                state = add_to_bird(state, player, where, eggs=1)
                return _pop(state, replace(task, remaining=n - 1))
            return None
        case EggBonusTask():
            return None if sum(board.food) > 0 and eggable(state, table, player) else _pop(state)
        case DrawTask(remaining=n, bonus=bonus):
            if n == 0 or not (any(state.tray) or state.deck or state.discard):
                has_egg = any(board.bird_at(p).eggs > 0 for p in board.placements())
                return _pop(state, *((DrawBonusTask(),) if n == 0 and bonus and has_egg else ()))
            return None
        case DrawBonusTask():
            has_egg = any(board.bird_at(p).eggs > 0 for p in board.placements())
            return None if has_egg else _pop(state)
        case TuckTask():
            return None if board.hand else _pop(state)
        case PowersTask(habitat=habitat, next_index=idx, played=played):
            return _settle_power(state, table, habitat, idx, played)
    raise AssertionError(f"未知の決定: {task}")


def _settle_power(
    state: WingspanState, table: CardTable, habitat: Habitat, idx: int, played: bool
) -> WingspanState | None:
    player = state.to_move
    row = state.players[player].row(habitat)
    if idx < 0 or idx >= len(row):
        return _pop(state)
    at = Placement(habitat, idx)
    power = table.bird(row[idx].name).power
    wanted = Timing.WHEN_PLAYED if played else Timing.WHEN_ACTIVATED
    after: tuple[Task, ...] = () if played else (PowersTask(habitat, idx - 1),)
    if power.timing is wanted and power.kind in powers.AUTO:
        state = powers.AUTO[power.kind](state, table, player, at, power)
        return replace(state, queue=after + state.queue[1:])
    if power.timing is wanted and power.kind in powers.DECIDE:
        can = powers.DECIDE[power.kind][0]
        if can(state, table, player, at, power):
            return None
    return _pop(state, *after)
