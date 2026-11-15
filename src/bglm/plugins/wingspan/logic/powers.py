"""鳥の能力(実装済みの種類だけ。出典は各札の文と付録 A p.6〜12)。

- AUTO: 使って損の無い能力(無料で得る、結果が乱数だけ)。決定を挟まず自動で使う(R p.10 は任意だが、使わない理由が無い)
- DECIDE: 費用や選択がある能力。UsePower / SkipPower を決定として出す
- PINK: 桃色(手番と手番の間に 1 回。相手の行動で起きる。R p.10)
- 上のどれでもない kind(Unmodeled): 効果なしとして進める。実機では、案内が出ればスキップする(02_DESIGN.md 論点 2)

実機のアプリは、AUTO の能力でも確認の案内を出す(✓ / ×)。executor はそれを ✓ で進める。
"""

from collections.abc import Callable
from dataclasses import replace

from bglm.plugins.wingspan.logic.cards import CardTable
from bglm.plugins.wingspan.logic.helpers import (
    add_to_bird,
    draw_from_deck,
    egg_room,
    gain_food,
    next_rng,
    pop_deck,
    take_die,
)
from bglm.plugins.wingspan.logic.models import (
    FEEDER_DICE_FACES,
    INV_OR_SEED,
    Food,
    Habitat,
    Nest,
    Placement,
    Power,
    Timing,
)
from bglm.plugins.wingspan.logic.state import Task, TuckTask, WingspanState

Effect = Callable[[WingspanState, CardTable, int, Placement, Power], WingspanState]
DecideEffect = Callable[
    [WingspanState, CardTable, int, Placement, Power], tuple[WingspanState, tuple[Task, ...]]
]


def _food(power: Power) -> Food:
    return Food(str(power.param("food")))


def _count(power: Power) -> int:
    return int(power.param("count", 1))


# ---- AUTO ----


def _gain_supply(s: WingspanState, t: CardTable, p: int, at: Placement, w: Power) -> WingspanState:
    return gain_food(s, p, _food(w), _count(w))


def _all_gain_supply(
    s: WingspanState, t: CardTable, p: int, at: Placement, w: Power
) -> WingspanState:
    for q in range(len(s.players)):
        s = gain_food(s, q, _food(w), _count(w))
    return s


def _lay_egg_on_self(
    s: WingspanState, t: CardTable, p: int, at: Placement, w: Power
) -> WingspanState:
    room = egg_room(s, t, p, at)
    return add_to_bird(s, p, at, eggs=min(room, _count(w))) if room > 0 else s


def _all_draw_deck(
    s: WingspanState, t: CardTable, p: int, at: Placement, w: Power
) -> WingspanState:
    for q in range(len(s.players)):
        s = draw_from_deck(s, q, _count(w))
    return s


def _predator_look_top(
    s: WingspanState, t: CardTable, p: int, at: Placement, w: Power
) -> WingspanState:
    """山札の一番上を確認し、翼長が基準未満ならこの鳥の下に差し込む。そうでなければ捨て札(A p.11)。"""
    s, top = pop_deck(s, 1)
    if not top:
        return s
    if t.known(top[0]) and t.bird(top[0]).wingspan_cm < int(w.param("wingspan_under", 100)):
        return add_to_bird(s, p, at, tucked=1)
    return replace(s, discard=s.discard + top)


def _predator_roll_cache(
    s: WingspanState, t: CardTable, p: int, at: Placement, w: Power
) -> WingspanState:
    """餌箱の外にあるダイスをすべて振り、出目に指定の餌が 1 つでもあれば、この鳥の上に蓄える(A p.11)。"""
    outside = 5 - len(s.feeder)
    s, rng = next_rng(s)
    faces = [rng.choice(FEEDER_DICE_FACES) for _ in range(outside)]
    if _food(w).value in faces:
        return add_to_bird(s, p, at, cached=_count(w))
    return s


def _fewest_in_habitat_draw(
    s: WingspanState, t: CardTable, p: int, at: Placement, w: Power
) -> WingspanState:
    """その生息地の鳥が最も少ない各プレイヤー(同数はみんな)が、山札から引く。"""
    habitat = Habitat(str(w.param("habitat")))
    sizes = [len(b.row(habitat)) for b in s.players]
    fewest = min(sizes)
    for q, size in enumerate(sizes):
        if size == fewest:
            s = draw_from_deck(s, q, _count(w))
    return s


AUTO: dict[str, Effect] = {
    "gain_supply": _gain_supply,
    "all_gain_supply": _all_gain_supply,
    "lay_egg_on_self": _lay_egg_on_self,
    "all_draw_deck": _all_draw_deck,
    "predator_look_top_deck": _predator_look_top,
    "predator_roll_cache": _predator_roll_cache,
    "fewest_in_habitat_draw": _fewest_in_habitat_draw,
}

# ---- DECIDE ----


def _feeder_index(s: WingspanState, food: Food) -> int | None:
    """餌箱で、指定の餌を取れるダイスの位置(2 種の目は虫か種のどちらでも取れる)。"""
    if food.value in s.feeder:
        return s.feeder.index(food.value)
    if food in (Food.INVERTEBRATE, Food.SEED) and INV_OR_SEED in s.feeder:
        return s.feeder.index(INV_OR_SEED)
    return None


def _can_feeder_cache(s: WingspanState, t: CardTable, p: int, at: Placement, w: Power) -> bool:
    return _feeder_index(s, _food(w)) is not None


def _feeder_cache(
    s: WingspanState, t: CardTable, p: int, at: Placement, w: Power
) -> tuple[WingspanState, tuple[Task, ...]]:
    """餌箱から指定の餌を取り、この鳥の上に蓄える。蓄えずに手元へ取る選択は、まだ手に持たない。"""
    index = _feeder_index(s, _food(w))
    assert index is not None
    return add_to_bird(take_die(s, index), p, at, cached=_count(w)), ()


def _can_pay_food(s: WingspanState, t: CardTable, p: int, at: Placement, w: Power) -> bool:
    return s.players[p].count(_food(w)) >= 1


def _pay_food_tuck(
    s: WingspanState, t: CardTable, p: int, at: Placement, w: Power
) -> tuple[WingspanState, tuple[Task, ...]]:
    """餌 1 個を捨て、山札の上から引いた札をこの鳥の下に差し込む(A p.9〜10)。"""
    s = gain_food(s, p, _food(w), -1)
    s, taken = pop_deck(s, int(w.param("tuck", 1)))
    return add_to_bird(s, p, at, tucked=len(taken)), ()


def _can_tuck_from_hand(s: WingspanState, t: CardTable, p: int, at: Placement, w: Power) -> bool:
    return bool(s.players[p].hand)


def _tuck_then_gain(
    s: WingspanState, t: CardTable, p: int, at: Placement, w: Power
) -> tuple[WingspanState, tuple[Task, ...]]:
    return s, (TuckTask(at, then_food=_food(w)),)


def _tuck_then_lay(
    s: WingspanState, t: CardTable, p: int, at: Placement, w: Power
) -> tuple[WingspanState, tuple[Task, ...]]:
    return s, (TuckTask(at, then_lay=int(w.param("lay", 1))),)


DECIDE: dict[str, tuple[Callable[..., bool], DecideEffect]] = {
    "gain_feeder_cache": (_can_feeder_cache, _feeder_cache),
    "discard_food_tuck_from_deck": (_can_pay_food, _pay_food_tuck),
    "tuck_from_hand_then_gain": (_can_tuck_from_hand, _tuck_then_gain),
    "tuck_from_hand_then_lay": (_can_tuck_from_hand, _tuck_then_lay),
}

# ---- PINK ----


def trigger_pink(
    s: WingspanState, t: CardTable, mover: int, *, kind: str, habitat: Habitat | None = None
) -> WingspanState:
    """mover の行動で、他のプレイヤーの桃色の鳥が起きる。1 羽につき、次の自分の手番までに 1 回(R p.10)。"""
    for q in range(len(s.players)):
        if q == mover:
            continue
        for at in s.players[q].placements():
            bird = s.players[q].bird_at(at)
            power = t.bird(bird.name).power
            if power.timing is not Timing.BETWEEN_TURNS or power.kind != kind or bird.used:
                continue
            if habitat is not None and power.param("habitat") != habitat.value:
                continue
            s = _pink_effect(s, t, q, at, power)
            board = s.players[q]
            used = replace(board.bird_at(at), used=True)
            s = s.with_player(q, board.with_bird(at, used))
    return s


def _pink_effect(s: WingspanState, t: CardTable, q: int, at: Placement, w: Power) -> WingspanState:
    if w.kind == "on_opponent_play_habitat_gain_supply":
        return gain_food(s, q, _food(w), _count(w))
    if w.kind == "on_opponent_lay_eggs_lay_on_nest":
        wanted = Nest(str(w.param("nest")))
        for other in s.players[q].placements():
            nest = t.bird(s.players[q].bird_at(other).name).nest
            if other != at and nest in (wanted, Nest.STAR) and egg_room(s, t, q, other) > 0:
                return add_to_bird(s, q, other, eggs=1)
    return s


PINK_KINDS = ("on_opponent_play_habitat_gain_supply", "on_opponent_lay_eggs_lay_on_nest")


def is_modeled(kind: str) -> bool:
    return kind in AUTO or kind in DECIDE or kind in PINK_KINDS
