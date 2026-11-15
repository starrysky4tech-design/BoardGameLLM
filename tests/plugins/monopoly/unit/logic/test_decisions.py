"""実機の状態からの判断(logic/decisions.py)のテスト。

場面は、2026-11-05 の実機の対局。期待値は、実際に取った判断から手で書く。
"""

from bglm.plugins.monopoly.logic.decisions import Decider, LiveState
from bglm.plugins.monopoly.logic.models import Holding, MonopolyState, Player

SELF, AI = Player.SELF, Player.AI


def live(
    self_cash: int, ai_cash: int, holdings: dict[str, Holding] | None = None, **pos: int
) -> LiveState:
    positions = {SELF: pos.get("me", 0), AI: pos.get("ai", 0)}
    return LiveState(
        MonopolyState(cash={SELF: self_cash, AI: ai_cash}, holdings=holdings or {}), positions
    )


def test_passes_on_water_works_when_the_opponent_cannot_afford_it() -> None:
    # 実機: Water Works(₼150)。自分 ₼751、Dog は ₼100 しか持たない → 買わずにオークションへ
    assert Decider().buy(live(751, 100, ai=12, me=26), "Water Works") is False


def test_buys_a_property_worth_more_than_its_price() -> None:
    # Kentucky(₼220)は、方針の価値(約 246)が価格を上回る。自分 ₼751、Dog ₼600 なら買う
    assert Decider().buy(live(751, 600, me=21), "Kentucky Avenue") is True


def test_does_not_buy_a_utility_worth_less_than_its_price() -> None:
    # 会社の 1 つ目は、価値が価格の 0.8 倍。Dog の現金が十分でも、買わない(方針の仕様)
    assert Decider().buy(live(751, 600, me=28), "Water Works") is False


def test_cannot_buy_what_it_cannot_afford() -> None:
    # 実機: Park Place(₼350)。自分 ₼140 では買えない
    assert Decider().buy(live(140, 98, me=37), "Park Place") is False


def test_auction_bid_equals_the_opponents_cash() -> None:
    # 実機: Water Works のオークション。Dog の現金 ₼100 と同額で入札して落札した
    bid = Decider().auction_bid(live(751, 100), "Water Works", highest_bid=44)
    assert bid == 100


def test_auction_bid_for_boardwalk_matches_the_real_one() -> None:
    # 実機: Boardwalk(₼400)。Dog ₼155 と同額の ₼155 で落札した。自分の現金 ₼486、Dog の入札は 62
    bid = Decider().auction_bid(live(486, 155), "Boardwalk", highest_bid=62)
    assert bid == 155


def test_auction_raises_by_a_step_when_it_cannot_force_the_win() -> None:
    # Dog の現金が潤沢(₼1500)だと、同額 ₼1500 は上限を超える。すぐには降りず、上限の 1/8 の刻みで重ねる
    # 吊り上げの上限は、自分の価値に、許す損(定価の 10%)を足した額まで。刻みは、その上限の 1/8
    assert Decider().auction_bid(live(751, 1500), "Water Works", highest_bid=44) == 60


def test_auction_folds_when_the_highest_bid_reaches_the_limit() -> None:
    # 最高入札が、方針の上限(Water Works は定価 ₼150 まで)に達していれば、降りる
    assert Decider().auction_bid(live(751, 1500), "Water Works", highest_bid=400) is None


def test_no_builds_when_nothing_is_complete() -> None:
    assert Decider().builds(live(740, 31, {"Boardwalk": Holding(owner=SELF)})) == {}


def test_builds_when_the_opponent_approaches_the_group() -> None:
    # ライトブルー(Connecticut 9、Vermont 8、Oriental 6)を自分が持つ。Dog は入口(Oriental 6)の手前 5(位置 1)
    holdings = {
        n: Holding(owner=SELF) for n in ("Oriental Avenue", "Vermont Avenue", "Connecticut Avenue")
    }
    result = Decider().builds(live(836, 155, holdings, ai=1))
    assert sum(result.values()) > 0
    assert set(result) <= set(holdings)


def test_does_not_build_when_the_opponent_cannot_reach_the_group_next_turn() -> None:
    # ピンク(St. Charles 11、States 13、Virginia 14)。Dog は 25 にいて、次の手番では届かない
    holdings = {
        n: Holding(owner=SELF) for n in ("St. Charles Place", "States Avenue", "Virginia Avenue")
    }
    assert Decider().builds(live(836, 155, holdings, ai=25)) == {}


def test_jail_action_early_game_pays_bail() -> None:
    from bglm.plugins.monopoly.logic.jail import JailAction

    assert Decider().jail_action(live(1500, 1500)) is JailAction.PAY_BAIL


def test_funds_shortfall_and_first_funding_step() -> None:
    from bglm.plugins.monopoly.logic.funding import StepKind

    # 家賃を払って所持金が -₼90 になった。揃っていない街(Baltic)を、抵当に入れる
    holdings = {"Baltic Avenue": Holding(owner=SELF)}
    state_live = live(-90, 500, holdings, me=31)
    assert Decider().funds_shortfall(state_live) == 90
    step = Decider().funding_step(state_live)
    assert step is not None and step.kind is StepKind.MORTGAGE and step.name == "Baltic Avenue"


def test_no_funding_step_when_cash_is_enough() -> None:
    holdings = {"Baltic Avenue": Holding(owner=SELF)}
    assert Decider().funding_step(live(1500, 500, holdings, me=31)) is None


def test_blocking_the_fourth_railroad_is_worth_bidding_above_the_list_price() -> None:
    # 2026-11-08 の実機: Thimble が鉄道を 3 つ持ち、B&O Railroad(₼200)の競り。取られると賃料が ₼100 → ₼200 になる。
    # 自分 ₼619、Thimble ₼263。最高入札 ₼187 に対し、相手の現金と同額の ₼263 で入札して阻止する
    holdings = {
        "Reading Railroad": Holding(owner=AI),
        "Pennsylvania Railroad": Holding(owner=AI),
        "Short Line": Holding(owner=AI),
    }
    bid = Decider().auction_bid(
        live(619, 263, holdings, me=18, ai=36), "B&O Railroad", highest_bid=187
    )
    assert bid == 263


def test_a_railroad_the_opponent_barely_cares_about_is_still_capped_at_the_list_price() -> None:
    bid = Decider().auction_bid(live(619, 2000, {}, me=18, ai=36), "B&O Railroad", highest_bid=150)
    assert bid is None or bid <= 200


def test_buys_the_fourth_railroad_at_the_list_price_instead_of_passing_to_an_auction() -> None:
    # 2026-11-08 の反省: B&O Railroad を、購入画面で見送り(評価が定価を下回るとして)、競りで ₼263 を払った。
    # 阻止価値を含めた評価なら、定価 ₼200 で買う
    holdings = {
        "Reading Railroad": Holding(owner=AI),
        "Pennsylvania Railroad": Holding(owner=AI),
        "Short Line": Holding(owner=AI),
    }
    assert Decider().buy(live(619, 300, holdings, me=25, ai=36), "B&O Railroad") is True


def test_never_passes_a_deed_it_would_pay_more_than_the_list_price_for_at_an_auction() -> None:
    # 購入画面の判断と、競りの上限が食い違わない: 競りで定価以上を払う上限があるなら、定価で買う。
    # (相手が定価を払えないため、競りに回して安く落札する方針の場合だけ、例外)
    from bglm.plugins.monopoly.logic.catalogue import CATALOGUE

    decider = Decider()
    scenes = [
        live(900, 900, {}, me=10, ai=20),
        live(
            900,
            900,
            {"Reading Railroad": Holding(owner=AI), "Short Line": Holding(owner=AI)},
            me=3,
            ai=20,
        ),
        live(1500, 1500, {"Park Place": Holding(owner=SELF)}, me=30, ai=20),
        live(
            900,
            900,
            {"Vermont Avenue": Holding(owner=AI), "Connecticut Avenue": Holding(owner=AI)},
            me=5,
            ai=20,
        ),
    ]
    for scene in scenes:
        game = decider._game(scene)
        for name, deed in CATALOGUE.items():
            if name in scene.state.holdings:
                continue
            limit = decider.policy.auction_limit(game, SELF, deed)
            if limit >= deed.price and scene.state.cash[AI] >= deed.price:
                assert decider.buy(scene, name), (
                    f"{name}: 競りの上限 {limit} が定価 {deed.price} 以上なのに、購入を見送る"
                )


def test_funding_never_starts_in_advance_of_landing() -> None:
    # 最悪の支払い(Virginia のホテル ₼900)が現金 ₼300 を超えても、止まる前には、資産を売らない
    holdings = {
        "Virginia Avenue": Holding(owner=AI, houses=5),
        "Baltic Avenue": Holding(owner=SELF),
    }
    assert Decider().funds_shortfall(live(300, 400, holdings, me=6, ai=0)) == 0
    assert Decider().funding_step(live(300, 400, holdings, me=6, ai=0)) is None


# --- 相手の入札の上限の推定を使う競り ---


def decider_with_estimate(ratio_stop: float = 0.5) -> Decider:
    """相手が、定価の ratio_stop 倍で降りた観測を 1 つ持つ Decider。"""
    decider = Decider()
    decider.bid_model.record_ai_stop(deed_price=200, my_price=int(200 * ratio_stop), ai_cash=1000)
    return decider


def test_conservative_estimate_keeps_the_current_behaviour() -> None:
    # 観測が無い間は、相手の現金と同額(現行の動作)
    assert Decider().auction_bid(live(751, 100), "Water Works", highest_bid=44) == 100


def test_first_bid_probes_just_above_the_estimate() -> None:
    # Kentucky(定価 220)。相手の上限の推定は、定価の 50% = 110。相手の現金 600 と同額(600)より、安い 111
    bid = decider_with_estimate(0.5).auction_bid(
        live(751, 600, me=21), "Kentucky Avenue", highest_bid=0
    )
    assert bid == 111


def test_second_bid_after_the_probe_failed_falls_back_to_the_opponents_cash() -> None:
    # 相手の現金 200(自分の上限 220 の範囲)。最初は推定のすぐ上の 111。外れて相手が 150 まで上げてきたら、
    # 次の入札は、相手の現金と同額(200)
    decider = decider_with_estimate(0.5)
    state = live(751, 200, me=21)
    assert decider.auction_bid(state, "Kentucky Avenue", highest_bid=0) == 111
    assert decider.auction_bid(state, "Kentucky Avenue", highest_bid=150, first=False) == 200


def test_probe_is_not_used_when_it_exceeds_my_limit() -> None:
    # 推定 90% = 198 は、自分の現金から残す現金を引いた額を超える
    bid = decider_with_estimate(0.9).auction_bid(
        live(250, 600, me=21), "Kentucky Avenue", highest_bid=0
    )
    assert bid is None or bid <= 250


def test_purchase_is_passed_to_the_auction_when_the_estimate_is_low_enough() -> None:
    # Kentucky(定価 220、価値は定価より上)。推定の上限が 50%(110)なら、定価の 75%(165)以下。見送って競りへ
    decider = decider_with_estimate(0.5)
    assert decider.buy(live(751, 600, me=21), "Kentucky Avenue") is False
    assert Decider().buy(live(751, 600, me=21), "Kentucky Avenue") is True  # 推定が無ければ、買う


def test_purchase_is_not_passed_when_the_estimate_is_close_to_the_price() -> None:
    decider = decider_with_estimate(0.9)  # 198 > 165: 安くならない
    assert decider.buy(live(751, 600, me=21), "Kentucky Avenue") is True


def test_purchase_is_not_passed_when_the_opponent_holds_the_same_colour() -> None:
    # Indiana(相手が Kentucky を持つ)。相手が同色を持つ土地は、競りに回して相手に取られる危険を取らない
    holdings = {"Kentucky Avenue": Holding(owner=AI)}
    decider = decider_with_estimate(0.5)
    assert decider.buy(live(751, 600, holdings, me=23), "Indiana Avenue") is True


def test_purchase_that_completes_my_group_is_never_passed() -> None:
    # Illinois(自分が Kentucky と Indiana を持つ。取ると独占が完成する)。推定が低くても、定価で買う
    holdings = {
        "Kentucky Avenue": Holding(owner=SELF),
        "Indiana Avenue": Holding(owner=SELF),
    }
    decider = decider_with_estimate(0.5)
    assert decider.buy(live(751, 600, holdings, me=24), "Illinois Avenue") is True
