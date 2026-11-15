"""オークションの入札額(logic/auction_bid.py)のテスト。期待値は手で書く。"""

from bglm.plugins.monopoly.logic.auction_bid import winning_bid


def test_bid_equal_to_opponent_cash_wins() -> None:
    # 実機の例: 誰も入札していない。Dog の現金 65。同額の 65 で、Dog は上回れない
    assert winning_bid(highest_bid=0, opponent_cash=65, my_limit=500, my_cash=621) == 65


def test_opponent_already_bid_but_still_can_outbid() -> None:
    # Dog が 44 を入札済み。Dog の現金 100。100 と同額なら、Dog は上回れない
    assert winning_bid(highest_bid=44, opponent_cash=100, my_limit=500, my_cash=751) == 100


def test_opponent_cannot_reach_the_next_bid() -> None:
    # Dog の現金 40 しかなく、最高入札額 62(自分の入札済み分ではなく、Dog 自身のものとして 62 は不整合)。
    # 相手の現金が最高入札額 + 1 に届かないなら、最高入札額 + 1 で足りる
    assert winning_bid(highest_bid=62, opponent_cash=40, my_limit=500, my_cash=621) == 63


def test_limit_below_the_needed_bid_means_fold() -> None:
    assert winning_bid(highest_bid=0, opponent_cash=300, my_limit=180, my_cash=621) is None


def test_cash_below_the_needed_bid_means_fold() -> None:
    assert winning_bid(highest_bid=0, opponent_cash=155, my_limit=500, my_cash=100) is None


def test_broke_opponent_needs_only_one_above_the_highest() -> None:
    assert winning_bid(highest_bid=0, opponent_cash=0, my_limit=100, my_cash=100) == 1


def test_raising_bid_adds_a_step_within_the_limit() -> None:
    from bglm.plugins.monopoly.logic.auction_bid import raising_bid

    assert raising_bid(highest_bid=109, my_limit=156, my_cash=1450) == 128  # 刻みは 156 // 8 = 19
    assert raising_bid(highest_bid=150, my_limit=156, my_cash=1450) == 156  # 上限で止める
    assert raising_bid(highest_bid=156, my_limit=156, my_cash=1450) is None  # 上限に達したら降りる
    assert raising_bid(highest_bid=109, my_limit=500, my_cash=112) == 112  # 現金を超えない


# --- 相手の上限の推定を使う入札 ---

from bglm.plugins.monopoly.logic.auction_bid import (  # noqa: E402
    DRAIN_MAX_REGRET,
    drain_bid,
    probe_bid,
)


def test_probe_bids_just_above_the_estimated_ceiling() -> None:
    # 定価 200 の土地。相手の上限の推定 120、相手の現金 400。121 から入札する(400 と同額より安い)
    assert (
        probe_bid(highest_bid=0, ceiling=120, my_limit=200, my_cash=600, opponent_cash=400) == 121
    )


def test_probe_respects_the_highest_bid() -> None:
    assert (
        probe_bid(highest_bid=150, ceiling=120, my_limit=200, my_cash=600, opponent_cash=400) == 151
    )


def test_probe_returns_none_when_it_would_not_be_cheaper() -> None:
    # 推定が相手の現金と同じ(保守的な値)なら、同額で入札する方法(winning_bid)へ戻る
    assert probe_bid(0, ceiling=400, my_limit=500, my_cash=600, opponent_cash=400) is None


def test_probe_returns_none_beyond_my_limit_or_cash() -> None:
    assert probe_bid(0, ceiling=190, my_limit=150, my_cash=600, opponent_cash=400) is None
    assert probe_bid(0, ceiling=190, my_limit=500, my_cash=150, opponent_cash=400) is None


def test_drain_raises_by_a_step_below_the_estimated_ceiling() -> None:
    # 定価 150、自分の価値 120、推定の上限 150(余裕 10% を引いて 135)、現金 600、残す現金 110
    bid = drain_bid(
        44, ceiling=150, my_cash=600, keep=110, my_value=120, deed_price=150, conservative=False
    )
    assert bid is not None and 44 < bid <= 135


def test_drain_never_exceeds_value_plus_the_allowed_regret() -> None:
    cap = 120 + int(DRAIN_MAX_REGRET * 150)
    bid = drain_bid(
        cap - 1,
        ceiling=1000,
        my_cash=900,
        keep=110,
        my_value=120,
        deed_price=150,
        conservative=False,
    )
    assert bid is not None and bid <= cap
    assert (
        drain_bid(
            cap,
            ceiling=1000,
            my_cash=900,
            keep=110,
            my_value=120,
            deed_price=150,
            conservative=False,
        )
        is None
    )


def test_drain_never_goes_below_the_cash_to_keep() -> None:
    bid = drain_bid(
        10, ceiling=1000, my_cash=200, keep=150, my_value=500, deed_price=300, conservative=False
    )
    assert bid is not None and bid <= 200 - 150


def test_drain_uses_a_wider_margin_when_the_estimate_is_unknown() -> None:
    sure = drain_bid(
        0, ceiling=300, my_cash=900, keep=100, my_value=900, deed_price=300, conservative=False
    )
    unsure = drain_bid(
        0, ceiling=300, my_cash=900, keep=100, my_value=900, deed_price=300, conservative=True
    )
    assert sure is not None and unsure is not None and unsure <= sure
    # 上限は、推定の 90%(確かなとき)と 70%(不明のとき)
    top_sure = drain_bid(269, 300, 900, 100, 900, 300, False)
    top_unsure = drain_bid(209, 300, 900, 100, 900, 300, True)
    assert top_sure is not None and top_sure <= 270
    assert top_unsure is not None and top_unsure <= 210
    assert drain_bid(270, 300, 900, 100, 900, 300, False) is None
    assert drain_bid(210, 300, 900, 100, 900, 300, True) is None
