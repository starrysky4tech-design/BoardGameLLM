"""模擬エンジンの単体テスト。サイコロとカードの順序を固定して、ご指示のルールどおりに動くことを確かめる。"""

from collections.abc import Callable, Iterator

from bglm.plugins.monopoly.logic.cards import (
    CHANCE_CARDS,
    COMMUNITY_CHEST_CARDS,
    Card,
    CardKind,
)
from bglm.plugins.monopoly.logic.engine import START_CASH, Game
from bglm.plugins.monopoly.logic.models import Deed, Holding, Player, Trade
from bglm.plugins.monopoly.logic.policies import ExpectedValuePolicy, GreedyPolicy

SELF, AI = Player.SELF, Player.AI


class PassivePolicy:
    """買わず、入札もせず、何も管理しない。移動と支払いだけを確かめるため。"""

    def wants_to_buy(self, game: Game, player: Player, deed: Deed) -> bool:
        return False

    def auction_limit(self, game: Game, player: Player, deed: Deed) -> int:
        return 0

    def manage(self, game: Game, player: Player) -> None:
        return None

    def propose_trades(self, game: Game, player: Player) -> list[Trade]:
        return []

    def respond_to_trade(self, game: Game, player: Player, proposer: Player, trade: Trade) -> bool:
        return False


class FixedLimit(PassivePolicy):
    def __init__(self, limit: int) -> None:
        self.limit = limit

    def auction_limit(self, game: Game, player: Player, deed: Deed) -> int:
        return self.limit


def dice(*rolls: tuple[int, int]) -> Callable[[], tuple[int, int]]:
    it: Iterator[tuple[int, int]] = iter(rolls)
    return lambda: next(it)


def make(
    *rolls: tuple[int, int], chance: list[Card] | None = None, chest: list[Card] | None = None
) -> Game:
    return Game(
        {SELF: PassivePolicy(), AI: PassivePolicy()},
        dice=dice(*rolls),
        chance_order=chance,
        chest_order=chest,
    )


def card(deck: tuple[Card, ...], kind: CardKind, **match: int) -> Card:
    return next(
        c for c in deck if c.kind is kind and all(getattr(c, k) == v for k, v in match.items())
    )


# --- 移動と GO ---


def test_passing_go_pays_the_salary_and_exact_stop_on_go_also_pays() -> None:
    game = make((3, 4))  # 38 + 7 = 45 → 5(Reading Railroad。誰も買わず、オークションも不成立)
    game.position[SELF] = 38
    game.play_turn()
    assert game.position[SELF] == 5
    assert game.cash(SELF) == START_CASH + 200

    game = make((2, 4))  # 34 + 6 = 40 → ちょうど GO
    game.position[SELF] = 34
    game.play_turn()
    assert game.position[SELF] == 0
    assert game.cash(SELF) == START_CASH + 200


def test_income_tax_and_luxury_tax() -> None:
    game = make((1, 3))  # 0 + 4 = 4(所得税)
    game.play_turn()
    assert game.cash(SELF) == START_CASH - 200
    game = make((3, 5))  # 30 + 8 = 38(ラグジュアリー税)
    game.position[SELF] = 30
    game.play_turn()
    assert game.cash(SELF) == START_CASH - 100


def test_landing_on_an_opponents_deed_pays_the_rent() -> None:
    game = make((1, 2))  # 0 + 3 = 3 (Baltic Avenue。賃料 4)
    game.state = game.state.__class__(
        cash=game.state.cash, holdings={"Baltic Avenue": Holding(owner=AI)}
    )
    game.play_turn()
    assert game.cash(SELF) == START_CASH - 4
    assert game.cash(AI) == START_CASH + 4


def test_doubles_roll_again_and_three_doubles_go_to_jail() -> None:
    game = make((1, 1), (2, 2), (3, 3))
    game.play_turn()
    assert game.jail_rest[SELF] == 0
    assert game.position[SELF] == 10


def test_a_double_gives_another_roll() -> None:
    game = make((1, 1), (1, 2))  # 2(Community Chest)→ 5(Reading)
    game.play_turn()
    assert game.position[SELF] == 5


# --- 刑務所(ご指示) ---


def test_landing_on_go_to_jail_sends_the_player_to_jail() -> None:
    game = make((3, 4))  # 23 + 7 = 30
    game.position[SELF] = 23
    game.play_turn()
    assert game.position[SELF] == 10
    assert game.jail_rest[SELF] == 0


def test_a_double_in_jail_frees_for_nothing_and_moves_by_the_roll_without_rolling_again() -> None:
    # 実機の確認(2026-11-01): ゾロ目で M50 を払わずに出て、4 マス進んだ
    game = make((2, 2))  # 10 + 4 = 14(Virginia Avenue。誰も買わない)
    game.jail_rest[SELF] = 0
    game.position[SELF] = 10
    game.play_turn()
    assert game.jail_rest[SELF] is None
    assert game.position[SELF] == 14
    assert game.cash(SELF) == START_CASH


def test_third_missed_roll_pays_50_and_moves_by_that_roll() -> None:
    # 実機の確認(2026-11-01): 3 回目の出目 7 で保釈金 M50 を払い、その 7 マス進んだ
    # 2 回の休みは自分と相手の出目(1,2)。3 回目は (1,3) で 10 + 4 = 14(Virginia Avenue。誰も買わない)
    game = make((1, 2), (1, 2), (1, 2), (1, 2), (1, 3))
    game.jail_rest[SELF] = 0
    game.position[SELF] = 10
    for _ in range(2):  # 自分の番が 2 回(間に相手の番)
        game.play_turn()  # SELF: 休み
        game.play_turn()  # AI
    game.play_turn()  # SELF: 3 回目
    assert game.jail_rest[SELF] is None
    assert game.position[SELF] == 14
    assert game.cash(SELF) == START_CASH - 50


def test_a_get_out_of_jail_card_frees_the_player_for_nothing() -> None:
    game = make((1, 2))
    game.jail_rest[SELF] = 0
    game.position[SELF] = 10
    game.jail_cards[SELF].append("chance")
    game.play_turn()
    assert game.jail_rest[SELF] is None
    assert game.cash(SELF) == START_CASH  # 罰金なし
    assert game.position[SELF] == 13  # 釈放後に、そのまま振って進む


# --- カード ---


def test_advance_to_go_card_pays_200_once() -> None:
    go = card(CHANCE_CARDS, CardKind.MOVE_TO, target=0)
    game = make((3, 4), chance=[go])  # 0 + 7 = 7(Chance)→ GO に進む
    game.play_turn()
    assert game.position[SELF] == 0
    assert game.cash(SELF) == START_CASH + 200


def test_nearest_railroad_card_pays_double_rent_to_the_owner() -> None:
    nearest = card(CHANCE_CARDS, CardKind.NEAREST_RAILROAD)
    game = make((3, 4), chance=[nearest])  # 7(Chance)→ 15(Pennsylvania Railroad)
    game.state = game.state.__class__(
        cash=game.state.cash, holdings={"Pennsylvania Railroad": Holding(owner=AI)}
    )
    game.play_turn()
    assert game.position[SELF] == 15
    assert game.cash(SELF) == START_CASH - 50  # 賃料 25 の 2 倍


def test_go_to_jail_card_and_pay_each_player_card() -> None:
    jail = card(CHANCE_CARDS, CardKind.GO_TO_JAIL)
    game = make((3, 4), chance=[jail])
    game.play_turn()
    assert game.position[SELF] == 10 and game.jail_rest[SELF] == 0

    each = card(CHANCE_CARDS, CardKind.PAY_EACH)
    game = make((3, 4), chance=[each])
    game.play_turn()
    assert game.cash(SELF) == START_CASH - 50
    assert game.cash(AI) == START_CASH + 50


def test_repairs_card_counts_houses_and_hotels() -> None:
    repairs = card(CHANCE_CARDS, CardKind.REPAIRS)
    game = make((3, 4), chance=[repairs])
    game.state = game.state.__class__(
        cash=game.state.cash,
        holdings={
            "Kentucky Avenue": Holding(owner=SELF, houses=2),
            "Indiana Avenue": Holding(owner=SELF, houses=5),  # ホテル
        },
    )
    game.play_turn()
    assert game.cash(SELF) == START_CASH - (2 * 25 + 100)


def test_in_game_amounts_are_used_for_the_two_cards_that_differ_from_the_list() -> None:
    stock = [c for c in COMMUNITY_CHEST_CARDS if "株式売却" in c.text][0]
    school = [c for c in COMMUNITY_CHEST_CARDS if "教育費" in c.text][0]
    assert stock.amount == 50 and school.amount == 50


# --- オークションと破産 ---


def test_auction_winner_pays_one_more_than_the_other_limit() -> None:
    game = Game({SELF: FixedLimit(100), AI: FixedLimit(30)}, dice=dice((1, 2)))  # 3: Baltic
    game.play_turn()
    assert game.state.holdings["Baltic Avenue"].owner is SELF
    assert game.cash(SELF) == START_CASH - 31


def test_nobody_bids_leaves_the_deed_unowned() -> None:
    game = make((1, 2))
    game.play_turn()
    assert "Baltic Avenue" not in game.state.holdings


def test_bankruptcy_ends_the_game_with_the_other_player_as_the_winner() -> None:
    game = make((3, 4), chance=[card(CHANCE_CARDS, CardKind.PAY_EACH)])
    game.state = game.state.__class__(cash={SELF: 10, AI: START_CASH}, holdings={})
    game.play_turn()
    assert game.winner is AI


def test_liquidation_mortgages_a_deed_before_going_bankrupt() -> None:
    game = make((1, 3))  # 所得税 200
    game.state = game.state.__class__(
        cash={SELF: 100, AI: START_CASH}, holdings={"Reading Railroad": Holding(owner=SELF)}
    )
    game.play_turn()
    assert game.winner is None
    assert game.state.holdings["Reading Railroad"].mortgaged
    assert game.cash(SELF) == 100 - 200 + 100  # 抵当価値 100


# --- 一局を通して ---


def test_full_games_finish_with_a_winner_and_no_negative_cash_for_the_winner() -> None:
    for seed in range(20):
        for make_a, make_b in ((ExpectedValuePolicy, GreedyPolicy), (GreedyPolicy, GreedyPolicy)):
            game = Game({SELF: make_a(), AI: make_b()}, seed=seed)
            winner = game.run()
            assert winner in (SELF, AI)
            assert game.cash(winner) >= 0 or game.decided_by_cap
            for holding in game.state.holdings.values():
                assert 0 <= holding.houses <= 5


def test_same_seed_gives_the_same_game() -> None:
    def run() -> tuple[Player | None, int]:
        game = Game({SELF: ExpectedValuePolicy(), AI: GreedyPolicy()}, seed=7)
        game.run()
        return game.winner, game.turns

    assert run() == run()
