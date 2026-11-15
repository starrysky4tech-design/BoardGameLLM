"""方針どうしを自己対戦させて、勝率を測る。先手と後手は、交互に入れ替える。"""

from collections.abc import Callable
from dataclasses import dataclass

from bglm.plugins.monopoly.logic.engine import Game, Policy
from bglm.plugins.monopoly.logic.models import Player

PolicyFactory = Callable[[], Policy]


@dataclass(frozen=True)
class MatchResult:
    games: int
    wins_a: int  # 方針 A(SELF の席)の勝ち
    wins_b: int
    decided_by_cap: int  # 手番の上限で決着した数(破産が起きなかった)
    average_turns: float

    @property
    def win_rate_a(self) -> float:
        return self.wins_a / self.games


def play_one(
    make_a: PolicyFactory, make_b: PolicyFactory, seed: int, first: Player, max_turns: int = 800
) -> Game:
    game = Game({Player.SELF: make_a(), Player.AI: make_b()}, seed=seed, first=first)
    game.run(max_turns)
    return game


def play_match(
    make_a: PolicyFactory,
    make_b: PolicyFactory,
    games: int,
    seed: int = 0,
    max_turns: int = 800,
) -> MatchResult:
    """A を SELF、B を AI の席に置いて games 局を行う。先手は局ごとに交互にする。"""
    wins_a = capped = turns = 0
    for i in range(games):
        first = Player.SELF if i % 2 == 0 else Player.AI
        game = play_one(make_a, make_b, seed + i, first, max_turns)
        wins_a += game.winner is Player.SELF
        capped += game.decided_by_cap
        turns += game.turns
    return MatchResult(
        games=games,
        wins_a=wins_a,
        wins_b=games - wins_a,
        decided_by_cap=capped,
        average_turns=turns / games,
    )
