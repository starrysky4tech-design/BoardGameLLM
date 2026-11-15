"""局面の評価値(自分から見た、ゲーム終了時の得点差の見込み)。重みは経験的な初期値で、自己対戦で調整する。

評価 = 今の得点差(自分 − 相手の最大)+ 資源の見込み + 行の強さ(残りの手番で何度使えるか)。
資源は「使い切れる分」だけ数える: 手札は残りの手番で置ける枚数まで、餌はその手札を払うのに要る分まで。
(手札を一律に高く数えると、払えない札を溜め続ける方針になる。実際にそうなった)
残りの手番が少ないほど、資源と行の強さの価値は下がる(点にならないまま終わるため)。
"""

from dataclasses import dataclass

from bglm.plugins.wingspan.logic import powers
from bglm.plugins.wingspan.logic.board import TURNS_PER_ROUND, action_strength
from bglm.plugins.wingspan.logic.models import HABITATS, Timing
from bglm.plugins.wingspan.logic.rules import WingspanRules
from bglm.plugins.wingspan.logic.state import WingspanState


@dataclass(frozen=True)
class Weights:
    food: float = 0.6  # 手札を払うのに要る餌 1 個
    food_extra: float = 0.15  # 余った餌 1 個
    card_base: float = 0.3  # 使い切れる手札 1 枚の基本値
    card_points: float = 0.35  # 手札の鳥の点 1 点(払える割合を掛ける)
    card_extra: float = 0.05  # 使い切れない手札 1 枚
    egg_room: float = 0.12  # 卵の空き 1 つ(後で卵 = 1 点にできる)
    row_slot: float = 0.35  # 行の強さ(その行の次の行動 1 回分の見込み)
    power: float = 0.5  # 実装済みの茶色の能力を持つ鳥 1 羽が、残りの手番で働く分
    horizon: float = 10.0  # 残りの手番がこれ以上なら資源を満額で数える
    turns_per_card: int = 3  # 手札 1 枚を置くのにかかる手番の見込み
    hand_limit: int = 7  # 手札の上限(戦略の方針。これを超えた札は、引く価値が無いものとして扱う)
    hand_over: float = 0.5  # 上限を超えた札 1 枚の減点


DEFAULT_WEIGHTS = Weights()


def remaining_turns(state: WingspanState, player: int) -> int:
    """これから自分が打てる手番の数(今のラウンドの残りと、後のラウンド)。"""
    later = sum(TURNS_PER_ROUND[state.round_index + 1 :])
    return state.players[player].cubes + later


def _hand_value(
    state: WingspanState, rules: WingspanRules, me: int, left: int, w: Weights
) -> float:
    board = state.players[me]
    table = rules.table
    known = sorted((table.bird(c) for c in board.hand if table.known(c)), key=lambda b: -b.points)
    usable = max(1, left // w.turns_per_card)
    mine, spare = known[:usable], known[usable:]
    need = sum(b.cost.total() for b in mine)
    have = sum(board.food)
    useful = min(have, need)
    afford = min(1.0, have / need) if need else 1.0
    value = w.food * useful + w.food_extra * (have - useful)
    value += sum(w.card_base + w.card_points * b.points * afford for b in mine)
    value += w.card_extra * len(
        spare
    )  # 読めない札は置けないので、価値に入れない(引き続ける動機にしない)
    value -= w.hand_over * max(0, len(board.hand) - w.hand_limit)  # 手札の上限を超えた分
    return value


def evaluate(
    state: WingspanState, rules: WingspanRules, me: int, weights: Weights = DEFAULT_WEIGHTS
) -> float:
    scores = [s.total for s in rules.scores(state)]
    others = [t for i, t in enumerate(scores) if i != me]
    value = float(scores[me] - max(others, default=0))
    if state.terminal:
        return value
    board = state.players[me]
    left = remaining_turns(state, me)
    scale = min(1.0, left / weights.horizon)
    table = rules.table
    resources = _hand_value(state, rules, me, left, weights)
    resources += weights.egg_room * sum(
        table.bird(b.name).egg_limit - b.eggs for b in board.birds()
    )
    engine = 0.0
    for habitat in HABITATS:
        row = board.row(habitat)
        n, convert = action_strength(habitat, len(row))
        engine += weights.row_slot * (n + (0.5 if convert else 0.0))
        for bird in row:
            power = table.bird(bird.name).power
            if power.timing is Timing.WHEN_ACTIVATED and powers.is_modeled(power.kind):
                engine += weights.power * min(1.0, left / 6)
    return value + scale * (resources + engine)
