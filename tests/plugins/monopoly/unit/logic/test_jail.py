"""刑務所の判断(logic/jail.py)のテスト。期待値は、指示(2026-11-08)から手で作る。"""

from bglm.plugins.monopoly.logic.catalogue import CATALOGUE
from bglm.plugins.monopoly.logic.jail import (
    MANY_UNOWNED,
    JailAction,
    decide_jail,
    wanted_deeds,
)
from bglm.plugins.monopoly.logic.models import Holding, MonopolyState, Player

SELF, AI = Player.SELF, Player.AI


def state(cash: int, holdings: dict[str, Holding]) -> MonopolyState:
    return MonopolyState(cash={SELF: cash, AI: 800}, holdings=holdings)


def owned_except(free: set[str], owner: Player = AI) -> dict[str, Holding]:
    """free 以外の全ての土地を、owner が持つ。"""
    return {n: Holding(owner=owner) for n in CATALOGUE if n not in free}


def test_early_game_many_unowned_pays_bail_without_a_card() -> None:
    assert len(CATALOGUE) - 0 >= MANY_UNOWNED
    action = decide_jail(state(1500, {}), CATALOGUE, SELF, jail_cards=0, failed_rolls=0, reserve=60)
    assert action is JailAction.PAY_BAIL


def test_early_game_uses_the_card_first() -> None:
    action = decide_jail(state(1500, {}), CATALOGUE, SELF, jail_cards=1, failed_rolls=0, reserve=60)
    assert action is JailAction.USE_CARD


def test_a_deed_that_completes_my_group_makes_me_leave_early() -> None:
    # 残りは Boardwalk だけ。Park Place は自分が持つ → 取ると濃青が揃う
    holdings = owned_except({"Boardwalk"})
    holdings["Park Place"] = Holding(owner=SELF)
    assert wanted_deeds(state(1000, holdings), CATALOGUE, SELF) == ["Boardwalk"]
    action = decide_jail(state(1000, holdings), CATALOGUE, SELF, 0, 0, reserve=60)
    assert action is JailAction.PAY_BAIL


def test_remaining_railroad_is_wanted_even_if_late() -> None:
    holdings = owned_except({"Reading Railroad"})
    assert wanted_deeds(state(1000, holdings), CATALOGUE, SELF) == ["Reading Railroad"]


def test_nothing_wanted_stays_and_waits_for_doubles() -> None:
    # 残りは、相手が同色を持つ街だけ(取っても揃わない)。保釈カードも無い
    holdings = owned_except({"Baltic Avenue"})
    holdings["Mediterranean Avenue"] = Holding(owner=AI)
    action = decide_jail(state(1000, holdings), CATALOGUE, SELF, 0, 0, reserve=60)
    assert action is JailAction.ROLL


def test_nothing_wanted_uses_the_card_only_on_the_third_turn() -> None:
    holdings = owned_except({"Baltic Avenue"})
    assert decide_jail(state(1000, holdings), CATALOGUE, SELF, 1, 1, reserve=60) is JailAction.ROLL
    assert (
        decide_jail(state(1000, holdings), CATALOGUE, SELF, 1, 2, reserve=60) is JailAction.USE_CARD
    )


def test_nothing_wanted_without_a_card_rolls_even_on_the_third_turn() -> None:
    # 3 回目の失敗で、ゲームが M50 を払わせて出す。先に払っても、同じ額
    holdings = owned_except({"Baltic Avenue"})
    assert decide_jail(state(1000, holdings), CATALOGUE, SELF, 0, 2, reserve=60) is JailAction.ROLL


def test_does_not_pay_bail_when_it_breaks_the_cash_reserve() -> None:
    action = decide_jail(state(100, {}), CATALOGUE, SELF, 0, 0, reserve=80)
    assert action is JailAction.ROLL
