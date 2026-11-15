"""巡回の山札(logic/patrol.py)のテスト。

期待値は実機(2026-11-11)の「巡回カード」画面と、ターン1開始時の地点の橙の数字から手で作った。
"""

import pytest

from bglm.plugins.maquis.logic.board import default_board
from bglm.plugins.maquis.logic.patrol import PatrolCard, PatrolDeck, full_deck, landing, load_cards


def test_full_deck_has_ten_cards() -> None:
    assert full_deck().size() == 10
    assert len(load_cards()) == 10


def test_cards_use_known_locations_with_three_distinct_places() -> None:
    board = default_board()
    for card in load_cards():
        assert len(set(card)) == 3
        assert all(loc in board.locations() for loc in card)


def test_first_choice_counts_match_the_orange_numbers_on_turn_1() -> None:
    # 観測: ターン1の開始時、橙の数字が出たのは 無線A・故買屋・無線B・ポン・レヴェック・食料品店で、どれも 2
    assert full_deck().first_choice_counts() == {
        "radio_a": 2,
        "black_market_fence": 2,
        "radio_b": 2,
        "pont_leveque": 2,
        "grocer": 2,
    }


def card(*places: str) -> PatrolCard:
    assert len(places) == 3
    return places[0], places[1], places[2]


# 3局目、ターン1に引かれた3枚(捨札の画面から。引いた順)と、出現した地点(ログ)
DRAW_1 = card("grocer", "pont_du_nord", "black_market_fence")  # 食料品店に出現
DRAW_2 = card("black_market_fence", "parade_street", "slums")  # 故買屋に出現
DRAW_3 = card("grocer", "slums", "doctor")  # ①の食料品店に巡回がいる → ②の貧民街に出現
# ターン2に引かれた1枚
DRAW_4 = card(
    "radio_b", "parade_street", "pont_leveque"
)  # 団員がポン・レヴェックにいる状態で、無線Bに出現


def test_patrol_goes_to_the_first_free_location_on_the_card() -> None:
    # 観測: 3局目のターン1。団員は畑(左)・カフェ・畑(右)にいて、カードの地点には関係しない
    agents = {"field_w", "cafe", "field_e"}
    assert landing(DRAW_1, frozenset(agents)) == "grocer"
    assert landing(DRAW_2, frozenset(agents | {"grocer"})) == "black_market_fence"
    # ①の食料品店に巡回がいるので、②の貧民街へ
    assert landing(DRAW_3, frozenset(agents | {"grocer", "black_market_fence"})) == "slums"


def test_agent_on_the_first_location_is_skipped() -> None:
    # 観測: 団員をポン・レヴェックに置くと、そこが①のカードは次の地点へ数えられた
    card_pl = card("pont_leveque", "black_market", "doctor")
    assert landing(card_pl, frozenset({"pont_leveque"})) == "black_market"
    assert landing(card_pl, frozenset()) == "pont_leveque"


def test_all_three_locations_occupied_is_none() -> None:
    assert landing(card("a", "b", "c"), frozenset({"a", "b", "c"})) is None


def draw_all(deck: PatrolDeck, *cards: PatrolCard) -> PatrolDeck:
    for c in cards:
        deck = deck.without(c)
    return deck


def test_counts_at_turn_2_start_after_three_draws() -> None:
    # 観測: ターン2の開始時の橙の数字は 故買屋1・無線A2・無線B2・ポン・レヴェック2(合計7)
    deck = draw_all(full_deck(), DRAW_1, DRAW_2, DRAW_3)
    assert deck.size() == 7
    counts = deck.landing_counts(frozenset())
    assert counts.places == {"black_market_fence": 1, "radio_a": 2, "radio_b": 2, "pont_leveque": 2}
    assert counts.blocked == 0


def test_counts_with_an_agent_on_pont_leveque() -> None:
    # 観測: ポン・レヴェックを選ぶと、数字が 故買屋1・ポン・デュ・ノール1・闇市1・無線A2・無線B2 に変わった
    deck = draw_all(full_deck(), DRAW_1, DRAW_2, DRAW_3)
    counts = deck.landing_counts(frozenset({"pont_leveque"}))
    assert counts.places == {
        "black_market_fence": 1,
        "pont_du_nord": 1,
        "black_market": 1,
        "radio_a": 2,
        "radio_b": 2,
    }


def test_counts_after_the_fourth_draw() -> None:
    # 観測: 無線Bに巡回が出た後(団員はポン・レヴェック)、数字は
    # 故買屋1・ポン・デュ・ノール1・闇市1・食料品店1・無線A2(合計6)
    deck = draw_all(full_deck(), DRAW_1, DRAW_2, DRAW_3, DRAW_4)
    counts = deck.landing_counts(frozenset({"pont_leveque", "radio_b"}))
    assert deck.size() == 6
    assert counts.places == {
        "black_market_fence": 1,
        "pont_du_nord": 1,
        "black_market": 1,
        "grocer": 1,
        "radio_a": 2,
    }


DRAW_5 = card(
    "black_market_fence", "pont_du_nord", "pont_leveque"
)  # 3ターン目の3枚目(故買屋に出現)
LAST = card("radio_a", "pont_leveque", "black_market")  # ターン3の終わりに残った1枚
DRAW_7 = card("radio_b", "grocer", "black_market")  # ターン4の2人目の後に引かれた(無線Bに出現)


def test_deck_has_one_card_left_at_turn_4_start() -> None:
    # 観測: ターン4の開始時、橙の数字は 無線A1 だけ(山札は残り1枚)。10 → 7 → 4 → 1
    full = full_deck()
    deck = draw_all(full, DRAW_1, DRAW_2, DRAW_3, DRAW_4)
    # ターン2: 引かれた4〜6枚目は、ポン・デュ・ノール・食料品店・無線Bの3枚(ログの出現地点から)
    deck = draw_all(
        deck,
        card("pont_leveque", "pont_du_nord", "doctor"),
        card("radio_b", "grocer", "black_market"),
    )
    # ターン3: 無線A(①の無線A)、医者(ポン・レヴェック・闇市・医者)、故買屋の3枚
    deck = draw_all(deck, card("radio_a", "parade_street", "grocer"))
    deck = draw_all(deck, card("pont_leveque", "black_market", "doctor"), DRAW_5)
    assert deck.remaining == ((LAST, 1),)
    assert deck.first_choice_counts() == {"radio_a": 1}


def test_empty_deck_is_reshuffled_from_all_ten_cards() -> None:
    # 観測: ターン4の2人目の配置で空の山札から引くと、山札は9枚(10枚から1枚引いた)になり、
    # 画面の数字は 故買屋2・バラダ2・ポン・レヴェック3・食料品店2(無線A・無線Bには巡回、畑には団員)
    full = full_deck()
    deck = PatrolDeck.of([LAST]).without(LAST)  # 1人目で最後の1枚を引いた
    assert deck.size() == 0
    deck = deck.drawn_from(DRAW_7, full)
    assert deck.size() == 9
    counts = deck.landing_counts(frozenset({"radio_a", "radio_b", "field_w", "field_e"}))
    assert counts.places == {
        "black_market_fence": 2,
        "parade_street": 2,
        "pont_leveque": 3,
        "grocer": 2,
    }


def test_non_empty_deck_is_not_reshuffled() -> None:
    full = full_deck()
    deck = full.without(DRAW_1)
    assert deck.drawn_from(DRAW_2, full).size() == 8


def test_drawing_removes_one_copy() -> None:
    deck = full_deck()
    card = ("radio_a", "parade_street", "grocer")
    after = deck.without(card)
    assert after.size() == 9
    assert after.count(card) == 0
    assert after.first_choice_counts()["radio_a"] == 1


def test_drawing_a_card_not_in_the_deck_is_an_error() -> None:
    # 読み取りの誤りを既定値で埋めず、止める
    deck = PatrolDeck.of([("a", "b", "c")])
    with pytest.raises(ValueError):
        deck.without(("x", "y", "z"))
    with pytest.raises(ValueError):
        deck.without(("a", "b", "c")).without(("a", "b", "c"))


def test_deck_ignores_order_and_counts_duplicates() -> None:
    a, b = ("a", "b", "c"), ("d", "e", "f")
    assert PatrolDeck.of([a, b, a]) == PatrolDeck.of([b, a, a])
    assert PatrolDeck.of([a, b, a]).count(a) == 2
