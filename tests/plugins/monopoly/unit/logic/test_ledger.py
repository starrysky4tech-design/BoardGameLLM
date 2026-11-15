"""Log の出来事からの所持金の計算(logic/ledger.py)のテスト。期待値は、2026-11-05 の実機の記録から手で書く。"""

from bglm.plugins.monopoly.logic import events as ev
from bglm.plugins.monopoly.logic.ledger import mismatches, predict
from bglm.plugins.monopoly.logic.log_replay import replay_log
from bglm.plugins.monopoly.logic.models import Player

SELF, AI = Player.SELF, Player.AI


def test_rent_moves_cash_from_payer_to_owner() -> None:
    # 実機: 自分が Illinois で Dog に家賃 ₼40。516 + 40 = 556 ではなく、自分 -40、Dog +40
    out = predict({SELF: 556, AI: 65}, [ev.RentPaid(SELF, 40, AI)], {})
    assert out == {SELF: 516, AI: 105}  # 実機の画面: 516 / 105


def test_go_salary_comes_from_tracked_passes() -> None:
    # 実機: 自分 32 + 8 = 40 → GO。給与 ₼200
    result = replay_log(
        {SELF: 32, AI: 10}, [ev.DiceRolled(SELF, 8, False), ev.LandedOn(SELF, "GO")]
    )
    assert result.go_passes == {SELF: 1}
    assert predict({SELF: 540, AI: 79}, [], result.go_passes)[SELF] == 740


def test_card_money_both_directions() -> None:
    out = predict(
        {SELF: 1000, AI: 100},
        [ev.MoneyReceived(SELF, 100, "Community Chest"), ev.MoneyLost(AI, 100, "Community Chest")],
        {},
    )
    assert out == {SELF: 1100, AI: 0}


def test_auction_price_is_paid_by_the_winner_once() -> None:
    # 「wins … for ₼65」と「won … at auction」は同じ落札の 2 行。金額のある行だけ数える
    events: list[ev.LogEvent] = [
        ev.AuctionWon(SELF, "St. James Place", 65),
        ev.AuctionWon(SELF, "St. James Place", None),
    ]
    assert predict({SELF: 621, AI: 65}, events, {})[SELF] == 556  # 実機: 621 → 556


def test_tax_bail_houses_and_mortgage() -> None:
    out = predict(
        {SELF: 1000, AI: 1000},
        [
            ev.LandedOn(SELF, "Income Tax"),  # -200
            ev.LandedOn(AI, "Luxury Tax"),  # -100
            ev.BailPosted(AI),  # -50
            ev.HousesBuilt(SELF, 2, "Connecticut Avenue"),  # -100(建設費 50)
            ev.HousesSold(AI, 1, "Baltic Avenue"),  # +25
            ev.Mortgaged(AI, "Indiana Avenue", 110),  # +110
        ],
        {},
    )
    assert out == {SELF: 700, AI: 985}


def test_dogs_double_roll_chain_and_jail_bail_from_the_real_log() -> None:
    # 実機の Log: Dog が刑務所の 3 回目(rolled 8)で保釈 ₼50、止まったマスの家賃 ₼28 を自分が受領
    events: list[ev.LogEvent] = [
        ev.DiceRolled(AI, 8, False),
        ev.BailPosted(AI),
        ev.RentPaid(AI, 28, SELF),
    ]
    out = predict({SELF: 516, AI: 105}, events, {})
    assert out == {SELF: 544, AI: 27}


def test_mismatch_reports_only_readable_differences() -> None:
    predicted = {SELF: 740, AI: 31}
    assert mismatches(predicted, {SELF: 740, AI: 31}) == []
    assert mismatches(predicted, {SELF: None, AI: None}) == []  # 読めなければ比べない
    found = mismatches(predicted, {SELF: 700, AI: None})
    assert len(found) == 1 and "-40" in found[0]


def test_tax_is_counted_once_even_when_both_lines_appear() -> None:
    # 実機: 「landed on Luxury Tax」と「pays ₼100 in Luxury Tax」の両方が出る。台帳は、止まったマスの税額だけ数える
    events: list[ev.LogEvent] = [
        ev.LandedOn(SELF, "Luxury Tax"),
        ev.TaxPaid(SELF, 100, "Luxury Tax"),
    ]
    assert predict({SELF: 1738, AI: 38}, events, {})[SELF] == 1638  # 実機: 1738 → 1638


def test_hotel_costs_one_house_price() -> None:
    assert (
        predict({SELF: 1000, AI: 185}, [ev.HotelBuilt(AI, "Baltic Avenue")], {})[AI] == 135
    )  # 建設費 50


def test_tax_reduces_cash() -> None:
    assert predict({SELF: 1000, AI: 344}, [ev.TaxPaid(AI, 200, "Income Tax")], {})[AI] == 144


def test_card_payment_to_the_other_player_is_reconciled_with_the_screen() -> None:
    from bglm.plugins.monopoly.logic.ledger import reconcile_card_transfers

    events: list[ev.LogEvent] = [ev.MoneyLost(SELF, 50, "Chance")]
    fixed, notes = reconcile_card_transfers({SELF: 1450, AI: 1500}, {SELF: 1450, AI: 1550}, events)
    assert fixed == {SELF: 1450, AI: 1550} and len(notes) == 1
    # 差が払った額と違えば、補わない
    fixed2, _ = reconcile_card_transfers({SELF: 1450, AI: 1500}, {SELF: 1450, AI: 1560}, events)
    assert fixed2[AI] == 1500


def test_card_collect_from_the_other_player_is_reconciled_with_the_screen() -> None:
    from bglm.plugins.monopoly.logic.ledger import reconcile_card_transfers

    events: list[ev.LogEvent] = [ev.MoneyReceived(AI, 10, "Community Chest")]
    fixed, notes = reconcile_card_transfers({SELF: 442, AI: 617}, {SELF: 432, AI: 617}, events)
    assert fixed == {SELF: 432, AI: 617} and len(notes) == 1
