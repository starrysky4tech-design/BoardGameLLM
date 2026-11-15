"""現金の食い違いの扱い(logic/cash_check.py)のテスト。`scripts/run_agent.py` から移した規則の回帰。"""

from bglm.plugins.monopoly.logic.cash_check import judge_cash
from bglm.plugins.monopoly.logic.events import AuctionWon
from bglm.plugins.monopoly.logic.models import Player

ME, AI = Player.SELF, Player.AI


def judge(
    predicted: dict[Player, int],
    observed: dict[Player, int | None],
    *,
    new_events: list | None = None,  # type: ignore[type-arg]
    unknown_lines: list[str] | None = None,
    gap: bool = False,
    stopped: bool = False,
):  # noqa: ANN201
    return judge_cash(
        predicted,
        observed,
        new_events=new_events or [],
        unknown_lines=unknown_lines or [],
        gap=gap,
        stopped=stopped,
    )


def test_agreement_has_no_diffs() -> None:
    v = judge({ME: 500, AI: 300}, {ME: 500, AI: 300})
    assert v.diffs == [] and v.cash == {ME: 500, AI: 300} and v.notes == []


def test_unreadable_screen_value_is_not_compared() -> None:
    v = judge({ME: 500, AI: 300}, {ME: 500, AI: None})
    assert v.diffs == [] and v.cash[AI] == 300  # 読めない側は、予測のまま


def test_small_difference_is_taken_from_the_screen() -> None:
    v = judge({ME: 500, AI: 300}, {ME: 495, AI: 300})
    assert v.diffs == [] and v.cash[ME] == 495 and v.notes


def test_one_sided_small_difference_without_ownership_events_is_taken() -> None:
    v = judge({ME: 500, AI: 300}, {ME: 450, AI: 300})  # -50: カードの受け払いの読み落とし
    assert v.diffs == [] and v.cash[ME] == 450


def test_one_sided_difference_over_the_limit_stays() -> None:
    v = judge({ME: 800, AI: 300}, {ME: 400, AI: 300})  # -400
    assert v.diffs and v.cash[ME] == 800


def test_one_sided_difference_with_an_auction_win_stays() -> None:
    won = AuctionWon(winner=AI, square="Water Works", price=150, direct=False)
    v = judge({ME: 500, AI: 300}, {ME: 450, AI: 300}, new_events=[won])
    assert v.diffs  # 所有が変わった。再同期へ


def test_one_sided_difference_with_gap_stays() -> None:
    v = judge({ME: 500, AI: 300}, {ME: 450, AI: 300}, gap=True)
    assert v.diffs


def test_unreadable_line_without_ownership_words_is_blamed() -> None:
    v = judge(
        {ME: 1000, AI: 300},
        {ME: 400, AI: 100},
        unknown_lines=["Thimb1e pa1d M200 in ren1"],
    )
    assert v.diffs == [] and v.cash == {ME: 400, AI: 100}


def test_unreadable_line_with_ownership_words_stays() -> None:
    v = judge(
        {ME: 1000, AI: 300},
        {ME: 400, AI: 100},
        unknown_lines=["Dog bought Boardwalk f0r M400"],
    )
    assert v.diffs


def test_symmetric_transfer_is_taken_from_the_screen() -> None:
    v = judge({ME: 1000, AI: 300}, {ME: 600, AI: 700})  # 自分 -400、相手 +400
    assert v.diffs == [] and v.cash == {ME: 600, AI: 700}


def test_symmetric_transfer_with_gap_stays() -> None:
    v = judge({ME: 1000, AI: 300}, {ME: 600, AI: 700}, gap=True)
    assert v.diffs


def test_asymmetric_large_difference_stays() -> None:
    v = judge({ME: 1000, AI: 300}, {ME: 390, AI: 100})
    assert v.diffs and v.cash == {ME: 1000, AI: 300}


def test_stopped_tracking_blocks_adoption() -> None:
    v = judge({ME: 500, AI: 300}, {ME: 450, AI: 300}, stopped=True)
    assert v.diffs


# --- 金額の読めなかった競りの逆算 ---

from bglm.plugins.monopoly.logic.cash_check import infer_unpriced_auction  # noqa: E402


def won(player: Player, square: str, price: int | None) -> AuctionWon:
    return AuctionWon(winner=player, square=square, price=price, direct=False)


def test_unpriced_auction_price_is_inferred_from_the_cash_difference() -> None:
    inferred = infer_unpriced_auction(
        [won(AI, "Water Works", None)],
        predicted={ME: 500, AI: 400},
        observed={ME: 500, AI: 200},
        ledger_owned={},
        board_owner={"Water Works": AI},
    )
    assert inferred == won(AI, "Water Works", 200)


def test_priced_twin_line_means_nothing_to_infer() -> None:
    assert (
        infer_unpriced_auction(
            [won(AI, "Water Works", 150), won(AI, "Water Works", None)],
            {ME: 500, AI: 400},
            {ME: 500, AI: 250},
            {},
            {"Water Works": AI},
        )
        is None
    )


def test_no_inference_if_the_board_does_not_show_the_winner_as_owner() -> None:
    args = ([won(AI, "Water Works", None)], {ME: 500, AI: 400}, {ME: 500, AI: 200}, {})
    assert infer_unpriced_auction(*args, {"Water Works": ME}) is None
    assert infer_unpriced_auction(*args, {"Water Works": None}) is None
    assert infer_unpriced_auction(*args, {}) is None


def test_no_inference_if_the_other_players_cash_also_differs() -> None:
    assert (
        infer_unpriced_auction(
            [won(AI, "Water Works", None)],
            {ME: 500, AI: 400},
            {ME: 450, AI: 200},
            {},
            {"Water Works": AI},
        )
        is None
    )


def test_no_inference_for_an_implausible_price() -> None:
    assert (
        infer_unpriced_auction(
            [won(AI, "Water Works", None)],
            {ME: 500, AI: 1000},
            {ME: 500, AI: 400},  # 600 = 定価 150 の 4 倍
            {},
            {"Water Works": AI},
        )
        is None
    )
    assert (
        infer_unpriced_auction(
            [won(AI, "Water Works", None)],
            {ME: 500, AI: 400},
            {ME: 500, AI: 450},  # 増えている
            {},
            {"Water Works": AI},
        )
        is None
    )


def test_no_inference_when_the_ledger_already_owns_it_or_two_squares_are_unpriced() -> None:
    one = [won(AI, "Water Works", None)]
    assert (
        infer_unpriced_auction(
            one, {ME: 500, AI: 400}, {ME: 500, AI: 200}, {"Water Works": 1}, {"Water Works": AI}
        )
        is None
    )
    two = [won(AI, "Water Works", None), won(AI, "Electric Company", None)]
    assert (
        infer_unpriced_auction(
            two,
            {ME: 500, AI: 400},
            {ME: 500, AI: 200},
            {},
            {"Water Works": AI, "Electric Company": AI},
        )
        is None
    )


def test_unreadable_cash_blocks_inference() -> None:
    assert (
        infer_unpriced_auction(
            [won(AI, "Water Works", None)],
            {ME: 500, AI: 400},
            {ME: 500, AI: None},
            {},
            {"Water Works": AI},
        )
        is None
    )
