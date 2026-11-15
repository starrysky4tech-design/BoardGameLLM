"""Log の行から出来事への変換(logic/events.py)のテスト。

入力は、2026-11-05 の実機の Log を OCR で読んだ文字列(誤読を含む)。期待値は、画面で読んだ内容から手で書く。
"""

import pytest

from bglm.plugins.monopoly.logic import events as ev
from bglm.plugins.monopoly.logic.models import Player

SELF, AI = Player.SELF, Player.AI


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Top Hat is starting its turn", ev.TurnStarted(SELF)),
        ("Dog is startingits turn", ev.TurnStarted(AI)),  # 空白の欠け
        ("Dogisstartingitsturn", ev.TurnStarted(AI)),  # 空白が全部欠けた
        ("Top Hat rolled 5", ev.DiceRolled(SELF, 5, doubles=False)),
        ("TopHat rolled 6", ev.DiceRolled(SELF, 6, doubles=False)),
        ("Dog rolled 4! Doubles!", ev.DiceRolled(AI, 4, doubles=True)),
        ("Top Hat rolled 2! Doubles!", ev.DiceRolled(SELF, 2, doubles=True)),
        ("Top Hat landed on New York Avenue", ev.LandedOn(SELF, "New York Avenue")),
        ("Top Hat landed on lllinois Avenue", ev.LandedOn(SELF, "Illinois Avenue")),  # I → l の誤読
        ("TopHatlandedonVermontAvenue", ev.LandedOn(SELF, "Vermont Avenue")),
        ("Top Hat landed onBoardwalk", ev.LandedOn(SELF, "Boardwalk")),
        ("Top Hat landed on Chance", ev.LandedOn(SELF, "Chance")),
        ("Top Hat paid M40 in rent to Dog.", ev.RentPaid(SELF, 40, AI)),  # ₼ → M
        ("Dog paid M90 in rent to Top Hat.", ev.RentPaid(AI, 90, SELF)),
        (
            "Dog passed on St. James Place. Starting auction.",
            ev.AuctionStarted(AI, "St. James Place"),
        ),
        ("Top Hat wins St. James Place for M65.", ev.AuctionWon(SELF, "St. James Place", 65)),
        ("Top Hat won St. James Place at auction", ev.AuctionWon(SELF, "St. James Place", None)),
        ("Oh no! Dog hasbeen sent to Jail.", ev.SentToJail(AI)),
        (
            "Top Hat built 2 houses on Connecticut Avenue",
            ev.HousesBuilt(SELF, 2, "Connecticut Avenue"),
        ),
    ],
)
def test_real_log_lines(line: str, expected: ev.LogEvent) -> None:
    assert ev.parse_line(line) == expected


@pytest.mark.parametrize(
    "line",
    [
        "Top Hat rolled 13",  # 範囲外の出目
        "Top Hat rolled 1",  # 2 個のダイスの合計は最低 2
        "Top Hat landed on Nowhere Street",  # 盤にない場所
        "Cat rolled 5",  # 知らないプレイヤー
        "Top Hat paid M40 in rent to Top Hat.",  # 自分に払う家賃は無い
        "something unrelated",
        "",
    ],
)
def test_unreadable_lines_are_unknown_not_guessed(line: str) -> None:
    assert isinstance(ev.parse_line(line), ev.UnknownLine)


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Dogrolled10", ev.DiceRolled(AI, 10, doubles=False)),
        ("TopHatrolled5", ev.DiceRolled(SELF, 5, doubles=False)),
        ("Dogis starting its turn", ev.TurnStarted(AI)),
        ("Top Hatrolled 9", ev.DiceRolled(SELF, 9, doubles=False)),
    ],
)
def test_partially_glued_lines_from_the_real_run(line: str, expected: ev.LogEvent) -> None:
    assert ev.parse_line(line) == expected


def test_bail_line() -> None:
    assert ev.parse_line("Dog has posted bail.") == ev.BailPosted(AI)
    assert ev.parse_line("Dog has postedbail.") == ev.BailPosted(AI)  # 空白の欠け


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("DogpaidM28inrent to TopHat.", ev.RentPaid(AI, 28, SELF)),
        ("TopHatpaidM52inrentto Dog.", ev.RentPaid(SELF, 52, AI)),
        ("Top Hat landed on GO", ev.LandedOn(SELF, "GO")),
    ],
)
def test_run_two_unknown_lines_are_now_read(line: str, expected: ev.LogEvent) -> None:
    assert ev.parse_line(line) == expected


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Dog sold 1 house on Mediterranean Avenue", ev.HousesSold(AI, 1, "Mediterranean Avenue")),
        ("Dogsold1houseonMediterraneanAvenue", ev.HousesSold(AI, 1, "Mediterranean Avenue")),
        ("Dogsold 1 house on Baltic Avenue", ev.HousesSold(AI, 1, "Baltic Avenue")),
        ("Dog sold 3 houses on Mediterranean Avenue", ev.HousesSold(AI, 3, "Mediterranean Avenue")),
        ("Dog mortgaged Indiana Avenue for M110", ev.Mortgaged(AI, "Indiana Avenue", 110)),
    ],
)
def test_sales_and_mortgages_from_the_real_run(line: str, expected: ev.LogEvent) -> None:
    assert ev.parse_line(line) == expected


def test_money_received_from_a_card() -> None:
    assert ev.parse_line("Top Hat receives M100 from Community Chest") == ev.MoneyReceived(
        SELF, 100, "Community Chest"
    )


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Dog loses M100 from Community Chest", ev.MoneyLost(AI, 100, "Community Chest")),
        ("Dog loses M1o0 from Community Chest", ev.MoneyLost(AI, 100, "Community Chest")),  # 0 → o
        (
            "Top Hat receives M1o0 from Community Chest",
            ev.MoneyReceived(SELF, 100, "Community Chest"),
        ),
    ],
)
def test_card_money_lines_and_digit_misreads(line: str, expected: ev.LogEvent) -> None:
    assert ev.parse_line(line) == expected


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Dog mortgaged lllinoisAvenueforM120", ev.Mortgaged(AI, "Illinois Avenue", 120)),
        ("Dog mortgaged Illinois Avenue for M120", ev.Mortgaged(AI, "Illinois Avenue", 120)),
    ],
)
def test_glued_mortgage_with_l_for_i(line: str, expected: ev.LogEvent) -> None:
    assert ev.parse_line(line) == expected


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Top Hat pays M100 in Luxury Tax.", ev.TaxPaid(SELF, 100, "Luxury Tax")),
        ("Top Hat pays M200 in Income Tax.", ev.TaxPaid(SELF, 200, "Income Tax")),
    ],
)
def test_tax_payment_line(line: str, expected: ev.LogEvent) -> None:
    assert ev.parse_line(line) == expected


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Dog built a hotel on Mediterranean Avenue", ev.HotelBuilt(AI, "Mediterranean Avenue")),
        ("Dog builta hotel on Baltic Avenue", ev.HotelBuilt(AI, "Baltic Avenue")),  # 実機の誤読
    ],
)
def test_hotel_built_lines_from_the_real_log(line: str, expected: ev.LogEvent) -> None:
    assert ev.parse_line(line) == expected


def test_mortgaged_square_no_rent_line() -> None:
    assert ev.parse_line("Property is mortgaged. No rent collected.") == ev.NoRentCollected()


def test_unmortgaged_line_from_the_real_log() -> None:
    assert ev.parse_line("Dog unmortgaged Pacific Avenue for M165") == ev.Unmortgaged(
        AI, "Pacific Avenue", 165
    )


def test_hotel_line_with_glued_player_name_from_the_real_log() -> None:
    assert ev.parse_line("TopHatbuilta hotel on States Avenue") == ev.HotelBuilt(
        SELF, "States Avenue"
    )


def test_other_game_pieces_are_read_as_the_opponent() -> None:
    assert ev.parse_line("Thimble rolled 7") == ev.DiceRolled(AI, 7, doubles=False)
    assert ev.parse_line("Thimble landed on Baltic Avenue") == ev.LandedOn(AI, "Baltic Avenue")
    assert ev.parse_line("Thimblelandedon Baltic Avenue") == ev.LandedOn(AI, "Baltic Avenue")
    assert ev.parse_line("Top Hat paid M20 in rent to Thimble") == ev.RentPaid(SELF, 20, AI)


def test_direct_purchase_line_from_the_real_log() -> None:
    assert ev.parse_line("Thimble bought Reading Railroad for M200") == ev.AuctionWon(
        AI, "Reading Railroad", 200, direct=True
    )


def test_game_start_line() -> None:
    assert ev.parse_line("Top Hat gets to go first.") == ev.GameStarted(SELF)


def test_glued_player_name_before_the_verb() -> None:
    assert ev.parse_line("Top Hatreceives M100 from Community Chest") == ev.MoneyReceived(
        SELF, 100, "Community Chest"
    )


def test_fully_glued_purchase_line_from_the_real_log() -> None:
    assert ev.parse_line("ThimbleboughtVentnorAvenueforM260") == ev.AuctionWon(
        AI, "Ventnor Avenue", 260, direct=True
    )


def test_trailing_o_after_digits_is_a_zero() -> None:
    assert ev.parse_line("Thimble receives M5o from Community Chest") == ev.MoneyReceived(
        AI, 50, "Community Chest"
    )


def test_trade_initiated_line_from_the_real_log() -> None:
    assert ev.parse_line("Thimble initiated a trade with Top Hat.") == ev.TradeInitiated(AI)


def test_sent_to_jail_line_without_the_exclamation_mark() -> None:
    assert ev.parse_line("Oh no Thimble has been sent to Jail") == ev.SentToJail(AI)
    assert ev.parse_line("Oh no! Thimble has been sent to Jail.") == ev.SentToJail(AI)


def test_misread_currency_sign_a_before_digits() -> None:
    assert ev.parse_line("Top Hat paid A6 in rent to Thimble") == ev.RentPaid(SELF, 6, AI)


def test_repeated_o_after_digits_are_zeros() -> None:
    assert ev.parse_line("Thimble receives M1oo from Community Chest") == ev.MoneyReceived(
        AI, 100, "Community Chest"
    )


def test_turn_started_line_with_a_misread_letter() -> None:
    assert ev.parse_line("TopHat is startino its turn") == ev.TurnStarted(SELF)


def test_fuzzy_turn_line_with_several_misreads() -> None:
    assert ev.parse_line("Ton Hatisstartinoitsturn") == ev.TurnStarted(SELF)
    assert isinstance(ev.parse_line("Thimble paid something odd"), ev.UnknownLine)


def test_trade_result_lines_from_the_real_log() -> None:
    assert ev.parse_line("Thimble accepted trade with Top Hat") == ev.TradeResult(AI, "accepted")
    assert ev.parse_line("Top Hat received M172 from Thimble") == ev.TradeResult(
        SELF, "cash", "172"
    )
    assert ev.parse_line("Top Hat received Kentucky Avenue from Thimble") == ev.TradeResult(
        SELF, "deed", "Kentucky Avenue"
    )
    assert ev.parse_line("Thimble received Baltic Avenue from Top Hat") == ev.TradeResult(
        AI, "deed", "Baltic Avenue"
    )


def test_shoe_is_me_and_wheelbarrow_is_the_opponent() -> None:
    assert ev.parse_line("Shoe rolled 7") == ev.DiceRolled(SELF, 7, doubles=False)
    assert ev.parse_line("Wheelbarrow landed on Baltic Avenue") == ev.LandedOn(AI, "Baltic Avenue")
    assert ev.parse_line("Shoe paid M20 in rent to Wheelbarrow") == ev.RentPaid(SELF, 20, AI)
    assert ev.parse_line("Wheelbarrowlandedon Baltic Avenue") == ev.LandedOn(AI, "Baltic Avenue")


def test_auction_start_line_without_the_period() -> None:
    assert ev.parse_line("Shoe passed on Virginia Avenue starting auction") == ev.AuctionStarted(
        SELF, "Virginia Avenue"
    )
    assert ev.parse_line(
        "Wheelbarrow passed on Baltic Avenue. Starting auction."
    ) == ev.AuctionStarted(AI, "Baltic Avenue")


def test_fully_glued_auction_win_with_a_misread_currency_sign() -> None:
    assert ev.parse_line("WheelbarrowwinsBalticAvenueforA40.") == ev.AuctionWon(
        AI, "Baltic Avenue", 40
    )


def test_fully_glued_trade_initiated_line() -> None:
    assert ev.parse_line("WheelbarrowinitiatedatradewithShoe.") == ev.TradeInitiated(AI)
