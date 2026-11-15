"""刑務所の判断(保釈カードを使う、保釈金を払う、ゾロ目を待つ)。画面には依存しない。

基準(2026-11-08 の指示。優先順):
 ① 誰も所有していない土地・鉄道・会社が、場に多く残っている
 ② 自分が取ると、同色グループが揃う、または鉄道・会社の収入が上がる土地が、残っている
   →①②のとき(早く出て、取りに行く): 1. 保釈カードがあれば使う  2. なければ M50 を払って、早めに出る
 ③ 欲しい土地・鉄道・会社が残っていない(AI が家・ホテルを建てて、支払いのリスクが高まっている)
   →できる限り、刑務所に残る: 1. ゾロ目を待つ  2. 3 回ゾロ目が出なければ、カードがあれば使う
     3. カードが無ければ、ゲームが決まりどおり M50 を払わせて出す(3 回目の Roll の失敗で自動)

「多く」の目安は、残りが 10 か所以上(28 か所の約 3 分の 1。暫定)。
"""

from collections.abc import Mapping
from enum import Enum

from bglm.plugins.monopoly.logic.board import JAIL_MAX_FAILS
from bglm.plugins.monopoly.logic.ledger import BAIL_FEE
from bglm.plugins.monopoly.logic.models import Deed, DeedKind, MonopolyState, Player

MANY_UNOWNED = 10
MAX_FAILED_ROLLS = JAIL_MAX_FAILS  # 3 回目の失敗で、ゲームが保釈金を払わせて出す


class JailAction(Enum):
    USE_CARD = "use_card"
    PAY_BAIL = "pay_bail"
    ROLL = "roll"  # ゾロ目を待つ(Roll する)


def unowned(state: MonopolyState, catalogue: Mapping[str, Deed]) -> list[str]:
    return [name for name in catalogue if name not in state.holdings]


def wanted_deeds(state: MonopolyState, catalogue: Mapping[str, Deed], me: Player) -> list[str]:
    """残っている土地のうち、取ると自分に得なもの(同色グループが揃う、または鉄道・会社が増える)。"""
    wanted: list[str] = []
    for name in unowned(state, catalogue):
        deed = catalogue[name]
        if deed.kind is not DeedKind.STREET:
            wanted.append(name)  # 鉄道・会社は、増えるほど収入が上がる
            continue
        mine = theirs = 0
        for other_name, holding in state.holdings.items():
            other = catalogue[other_name]
            if other.group == deed.group and other.kind is DeedKind.STREET:
                if holding.owner is me:
                    mine += 1
                else:
                    theirs += 1
        if mine == deed.group_size - 1 and theirs == 0:
            wanted.append(name)  # 取ると、自分の独占が完成する
    return wanted


def wants_to_leave_early(state: MonopolyState, catalogue: Mapping[str, Deed], me: Player) -> bool:
    """①か②が成り立つか(早く出て、土地を取りに行きたいか)。"""
    return len(unowned(state, catalogue)) >= MANY_UNOWNED or bool(
        wanted_deeds(state, catalogue, me)
    )


def decide_jail(
    state: MonopolyState,
    catalogue: Mapping[str, Deed],
    me: Player,
    jail_cards: int,
    failed_rolls: int,
    reserve: int,
) -> JailAction:
    """刑務所の中の手番で、まず何をするか。

    failed_rolls: ここまでにダブルが出なかった回数(0〜2)。reserve: 残す現金(保釈金を払った後も残す額)。
    """
    if wants_to_leave_early(state, catalogue, me):
        if jail_cards > 0:
            return JailAction.USE_CARD
        if state.cash[me] - BAIL_FEE >= reserve:
            return JailAction.PAY_BAIL
        return JailAction.ROLL  # 払うと、現金の予備を割る
    if failed_rolls >= MAX_FAILED_ROLLS - 1 and jail_cards > 0:
        return JailAction.USE_CARD  # 3 回目の手番。ゲームが罰金を払わせる前に、カードで出る
    return JailAction.ROLL
