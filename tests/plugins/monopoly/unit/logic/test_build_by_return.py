"""家を建てる判断(期待収益、policies.py の )のテスト。

基準: 「相手が次の手番でその土地に止まる確率 × 賃料の増分」÷ 建設費 が、下限以上のとき建てる。
均等に建てる規則のため、同色の他の土地を先に建てる分も含めた「束」で比べる。確率は `landing_odds`(手計算で確認済み)。
ピンク: St. Charles Place(11)、States Avenue(13)、Virginia Avenue(14)。建設費 ₼100。
"""

import pytest

from bglm.plugins.monopoly.logic.engine import Game
from bglm.plugins.monopoly.logic.landing_odds import next_turn_landing
from bglm.plugins.monopoly.logic.models import Holding, MonopolyState, Player
from bglm.plugins.monopoly.logic.policies import ExpectedValuePolicy, GreedyPolicy

SELF, AI = Player.SELF, Player.AI
PINK = ("St. Charles Place", "States Avenue", "Virginia Avenue")
ORANGE = ("St. James Place", "Tennessee Avenue", "New York Avenue")


def policy(**kwargs: object) -> ExpectedValuePolicy:
    kwargs.setdefault("build_min_return", 0.05)
    return ExpectedValuePolicy(**kwargs)  # type: ignore[arg-type]


def make_game(
    opponent_position: int,
    cash: int = 1000,
    groups: tuple[tuple[str, ...], ...] = (PINK,),
    houses: int = 0,
    opponent_jail: int | None = None,
) -> Game:
    game = Game({SELF: GreedyPolicy(), AI: GreedyPolicy()})
    game.state = MonopolyState(
        cash={SELF: cash, AI: 500},
        holdings={n: Holding(owner=SELF, houses=houses) for g in groups for n in g},
    )
    game.position[AI] = opponent_position
    game.position[SELF] = 0
    game.jail_rest[AI] = opponent_jail
    return game


def levels(game: Game, names: tuple[str, ...] = PINK) -> list[int]:
    return [game.state.holdings[n].houses for n in names]


def test_builds_when_the_opponent_can_reach_the_group() -> None:
    game = make_game(opponent_position=4)  # 4 から、11・13・14 までは 7・9・10 マス
    policy().manage(game, SELF)
    assert sum(levels(game)) > 0


def test_does_not_build_when_the_opponent_cannot_reach_the_group_next_turn() -> None:
    game = make_game(opponent_position=25)  # ピンクまで 26 マス以上。次の手番では届かない
    policy().manage(game, SELF)
    assert levels(game) == [0, 0, 0]


def test_does_not_build_once_the_opponent_is_past_the_group() -> None:
    game = make_game(opponent_position=20)
    policy().manage(game, SELF)
    assert levels(game) == [0, 0, 0]


def test_zero_gain_is_not_built_even_with_plenty_of_cash() -> None:
    game = make_game(opponent_position=25, cash=100000)
    policy().manage(game, SELF)
    assert levels(game) == [0, 0, 0]  # 止まる確率が 0 なら、現金に余裕があっても建てない


def test_first_house_goes_to_the_tile_the_opponent_is_most_likely_to_land_on() -> None:
    # 相手は 10。1 マス先の St. Charles(11)には、最低の出目 2 で届かない。Virginia(14)は 4 マス先
    game = make_game(opponent_position=10, cash=300)  # 1 軒だけ買える現金(残す現金を引いた後)
    policy(build_min_return=0.01).manage(game, SELF)
    built = {n: game.state.holdings[n].houses for n in PINK}
    assert built["Virginia Avenue"] == 1 and sum(built.values()) == 1


def test_evenness_rule_is_respected_when_building_more() -> None:
    game = make_game(opponent_position=4, cash=2000)
    policy(build_min_return=0.01).manage(game, SELF)
    assert max(levels(game)) - min(levels(game)) <= 1


def test_low_cash_does_not_build() -> None:
    game = make_game(opponent_position=4, cash=140)  # 残す現金(最低 ₼60 + 50)を割る
    policy().manage(game, SELF)
    assert levels(game) == [0, 0, 0]


def test_a_higher_threshold_builds_less() -> None:
    low, high = make_game(4, cash=2000), make_game(4, cash=2000)
    policy(build_min_return=0.01).manage(low, SELF)
    policy(build_min_return=0.5).manage(high, SELF)
    assert sum(levels(low)) > sum(levels(high))


def test_hotel_is_built_with_the_same_rule() -> None:
    game = make_game(opponent_position=4, cash=2000, houses=4)
    policy(build_min_return=0.01).manage(game, SELF)
    assert levels(game) == [5, 5, 5]


def test_a_jailed_opponent_is_less_likely_to_arrive() -> None:
    free = make_game(opponent_position=10, cash=2000)
    jailed = make_game(opponent_position=10, cash=2000, opponent_jail=0)
    p = policy(build_min_return=0.05)
    p.manage(free, SELF)
    p.manage(jailed, SELF)
    assert sum(levels(free)) >= sum(levels(jailed))


def test_the_group_with_the_higher_return_is_built_first() -> None:
    # 相手は 12。オレンジ(16・18・19)までは 4・6・7 マス、ピンクは通り過ぎている。現金は 1 軒ぶん
    game = make_game(opponent_position=12, cash=300, groups=(PINK, ORANGE))
    policy(build_min_return=0.01).manage(game, SELF)
    assert sum(levels(game, ORANGE)) == 1 and sum(levels(game)) == 0


def test_surplus_cash_lowers_the_threshold() -> None:
    # 相手は、グループの手前 12 マスほど。確率が低く、通常の下限では建てない。現金が非常に多いと建てる
    tight, rich = make_game(opponent_position=3, cash=400), make_game(3, cash=5000)
    p = policy(build_min_return=0.3, build_surplus=600, build_surplus_return=0.001)
    p.manage(tight, SELF)
    p.manage(rich, SELF)
    assert sum(levels(tight)) == 0 and sum(levels(rich)) > 0


def test_decision_uses_the_next_turn_landing_probability() -> None:
    odds = next_turn_landing(4)
    assert odds.at(11) > 0 and odds.at(13) > 0 and odds.at(14) > 0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"build_min_return": 0.0},
        {"build_min_return": 1.5},
        {"build_min_return": 0.1, "build_surplus_return": 0.2},
        {"build_surplus": -1},
    ],
)
def test_invalid_parameters_are_rejected(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        ExpectedValuePolicy(**kwargs)  # type: ignore[arg-type]
