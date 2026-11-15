"""相手の入札の上限の推定(logic/opponent_model.py)のテスト。"""

from bglm.plugins.monopoly.logic.opponent_model import BidModel


def test_without_observations_the_estimate_is_conservative() -> None:
    model = BidModel()
    assert model.conservative and model.ratio is None
    assert model.ceiling(200, ai_cash=350) == 350  # 相手は、現金の全額まで入札するとみなす


def test_a_stop_below_the_ai_cash_sets_the_estimate() -> None:
    model = BidModel()
    model.record_ai_stop(deed_price=200, my_price=120, ai_cash=500)  # 60%
    assert model.ratio == 0.6 and not model.conservative
    assert model.ceiling(300, ai_cash=1000) == 180
    assert model.ceiling(300, ai_cash=100) == 100  # 相手の現金が上限


def test_a_stop_caused_by_lack_of_ai_cash_is_not_an_observation() -> None:
    model = BidModel()
    model.record_ai_stop(deed_price=200, my_price=120, ai_cash=90)  # 相手は 120 に届かなかった
    assert model.conservative
    # 自分が「相手の現金と同額」で入札して落札した。相手は、上回れなかっただけ
    model.record_ai_stop(deed_price=200, my_price=120, ai_cash=120)
    assert model.conservative
    model.record_ai_stop(deed_price=200, my_price=120, ai_cash=121)  # 上回れたのに入札しなかった
    assert not model.conservative


def test_the_lowest_stop_is_used_but_never_below_an_observed_bid() -> None:
    model = BidModel()
    model.record_ai_stop(200, 100, 500)  # 50%
    model.record_ai_stop(100, 80, 500)  # 80%
    assert model.ratio == 0.5
    model.record_ai_bid(200, 130)  # 相手は、65% まで入札した。上限の推定が、それより低いはずが無い
    assert model.ratio == 0.65


def test_bids_alone_do_not_make_the_estimate_confident() -> None:
    model = BidModel()
    model.record_ai_bid(200, 150)
    assert model.conservative  # 下限だけでは、止まる額は分からない


def test_invalid_observations_are_ignored() -> None:
    model = BidModel()
    model.record_ai_bid(0, 10)
    model.record_ai_bid(100, 0)
    model.record_ai_stop(100, 0, 500)
    model.record_ai_stop(0, 50, 500)
    assert model.ai_bids == [] and model.ai_stops == []


def test_old_observations_are_dropped() -> None:
    model = BidModel(max_samples=3)
    for price in (50, 60, 70, 80, 90):
        model.record_ai_stop(100, price, 500)
    assert model.ai_stops == [0.7, 0.8, 0.9]


def test_round_trip_through_a_dict() -> None:
    model = BidModel()
    model.record_ai_bid(200, 150)
    model.record_ai_stop(200, 180, 500)
    assert BidModel.from_dict(model.to_dict()) == model
