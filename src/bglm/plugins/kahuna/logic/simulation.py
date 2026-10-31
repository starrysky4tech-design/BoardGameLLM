"""両者の手札を持つ自己対戦。画面なしで1ゲームを完走させ、ルールの矛盾や無限ループを見つける。

自分視点の KahunaState(rules.py)は相手の手札を持たない。ここでは両者の手札と山札の順序を持ち、
各プレイヤーに自分視点の盤面を渡して手を選ばせる。盤面の更新は rules.py の関数を使う。
決算後の山札の作り直し(捨て札を混ぜる。手札は残る)は、ルールページの記述による。アプリでの
確認はまだ(docs/ideas/Kahuna_アプリ内ルール.md の「未確認」)。途中終了は既定では適用しない。
"""

import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from bglm.core.models import TimeBudget
from bglm.plugins.kahuna.logic.models import (
    HAND_LIMIT,
    MARKET_SIZE,
    STICKS_PER_PLAYER,
    UNKNOWN_CARD,
    BoardDef,
    DiscardCard,
    DrawDeck,
    DrawMarket,
    KahunaMove,
    KahunaState,
    PassDraw,
    PlaceStick,
    Player,
    RemoveStick,
    default_board,
)
from bglm.plugins.kahuna.logic.rules import (
    KahunaRules,
    Ruleset,
    count_sticks,
    decide_winner,
    early_end_winner,
    place_stick,
    remove_stick,
    round_points,
)

MAX_MOVES_PER_TURN = 60
MAX_TURNS = 600


class Chooser(Protocol):
    def choose(
        self, state: KahunaState, legal: Sequence[KahunaMove], budget: TimeBudget
    ) -> KahunaMove: ...


class RandomChooser:
    """合法手から一様に選ぶ。基準となる弱い相手。"""

    def __init__(self, rng: random.Random) -> None:
        self._rng = rng

    def choose(
        self, state: KahunaState, legal: Sequence[KahunaMove], budget: TimeBudget
    ) -> KahunaMove:
        return self._rng.choice(list(legal))


@dataclass(frozen=True)
class GameResult:
    winner: Player | None  # Player.ME は先手(プレイヤー0)。None は引き分け
    scores: tuple[int, int]
    round3_points: tuple[int, int]
    turns: int
    early_end: bool


@dataclass
class Game:
    """絶対視点(プレイヤー0=先手、1=後手)の対戦の状態。"""

    rng: random.Random
    board: BoardDef = field(default_factory=default_board)
    ruleset: Ruleset = field(default_factory=Ruleset)
    sticks: tuple[Player | None, ...] = ()
    stones: tuple[Player | None, ...] = ()
    hands: list[list[int]] = field(default_factory=lambda: [[], []])
    market: list[int] = field(default_factory=list)
    deck: list[int] = field(default_factory=list)
    discard: list[int] = field(default_factory=list)
    round: int = 1
    scores: list[int] = field(default_factory=lambda: [0, 0])
    round3_points: list[int] = field(default_factory=lambda: [0, 0])
    must_draw: list[bool] = field(default_factory=lambda: [False, False])
    over: bool = False
    winner: Player | None = None
    early_end: bool = False
    turns: int = 0  # 何手番目か(play_game が更新する)

    def __post_init__(self) -> None:
        self.sticks = (None,) * len(self.board.lines)
        self.stones = (None,) * len(self.board.islands)
        cards = [i for i in range(len(self.board.islands)) for _ in range(2)]  # 各島2枚で24枚
        self.rng.shuffle(cards)
        for side in (0, 1):
            self.hands[side] = [cards.pop() for _ in range(3)]
        self.market = [cards.pop() for _ in range(MARKET_SIZE)]
        self.deck = cards

    # --- 視点の変換 -------------------------------------------------------------

    def view(self, side: int) -> KahunaState:
        """side の視点の盤面。自分の杖コマ・カフナコマは ME、相手のは OPPONENT。"""

        def mine(owner: Player | None) -> Player | None:
            if owner is None:
                return None
            return Player.ME if owner.value == side else Player.OPPONENT

        scores = (self.scores[side], self.scores[1 - side])
        round3 = (self.round3_points[side], self.round3_points[1 - side])
        return KahunaState(
            sticks=tuple(mine(o) for o in self.sticks),
            stones=tuple(mine(o) for o in self.stones),
            hand=tuple(sorted(self.hands[side])),
            market=tuple(sorted(self.market)),
            deck_count=len(self.deck),
            round=self.round,
            scores=scores,
            round3_points=round3,
            must_draw=self.must_draw[side],
            over=self.over,
            winner=None if self.winner is None else mine(self.winner),
        )

    # --- 手の適用 ---------------------------------------------------------------

    def apply(self, side: int, move: KahunaMove, rules: KahunaRules) -> bool:
        """side の手を適用する。手番が終わったら True。合法でなければ ValueError。"""
        if move not in rules.legal_moves(self.view(side)):
            raise ValueError(f"合法手ではない: side={side} {move!r}")
        player = Player(side)
        hand = self.hands[side]
        match move:
            case PlaceStick(card=card, line=line):
                self.sticks, self.stones = place_stick(
                    self.board, self.sticks, self.stones, line, player
                )
                hand.remove(card)
                self.discard.append(card)
            case RemoveStick(cards=cards, line=line):
                self.sticks, self.stones = remove_stick(self.board, self.sticks, self.stones, line)
                for card in cards:
                    hand.remove(card)
                    self.discard.append(card)
            case DiscardCard(card=card):
                hand.remove(card)
                self.discard.append(card)
            case DrawMarket(card=card):
                self.market.remove(card)
                hand.append(card)
                if self.deck:
                    self.market.append(self.deck.pop())
                self.must_draw[side] = False
                self.must_draw[1 - side] = False
                return self._finish_move(True)
            case DrawDeck():
                hand.append(self.deck.pop())
                self.must_draw[side] = False
                self.must_draw[1 - side] = False
                return self._finish_move(True)
            case PassDraw():
                self.must_draw[1 - side] = True
                self.must_draw[side] = False
                return self._finish_move(True)
        return self._finish_move(False)

    def _finish_move(self, turn_over: bool) -> bool:
        if self.ruleset.early_end_without_sticks:
            winner = early_end_winner(self.round, self.sticks)
            if winner is not None:
                self.over, self.winner, self.early_end = True, winner, True
        return turn_over

    # --- ラウンド・決算 ---------------------------------------------------------

    @property
    def cards_left(self) -> int:
        return len(self.deck) + len(self.market)

    def settle_round(self) -> None:
        """1・2ラウンド目の決算。山札は捨て札を混ぜて作り直し、手札は残す。"""
        gains = round_points(self.round, self.stones)
        self.scores[0] += gains[0]
        self.scores[1] += gains[1]
        self.round += 1
        self.rng.shuffle(self.discard)
        self.deck, self.discard = self.discard, []
        self.market = [self.deck.pop() for _ in range(min(MARKET_SIZE, len(self.deck)))]

    def final_scoring(self) -> None:
        gains = round_points(3, self.stones)
        self.scores[0] += gains[0]
        self.scores[1] += gains[1]
        self.round3_points = [gains[0], gains[1]]
        self.over = True
        self.winner = decide_winner(
            (self.scores[0], self.scores[1]),
            (self.round3_points[0], self.round3_points[1]),
            self.sticks,
        )

    # --- 不変条件(テストで確認する) --------------------------------------------

    def check_invariants(self) -> None:
        in_play = self.hands[0] + self.hands[1] + self.market + self.deck + self.discard
        counts = [in_play.count(i) for i in range(len(self.board.islands))]
        assert counts == [2] * len(self.board.islands), f"カードが増減した: {counts}"
        for side in (0, 1):
            assert len(self.hands[side]) <= HAND_LIMIT, f"手札が{HAND_LIMIT}枚を超えた"
            assert count_sticks(self.sticks, Player(side)) <= STICKS_PER_PLAYER
        for island, owner in enumerate(self.stones):
            if owner is None:
                continue
            mine = sum(1 for n in self.board.lines_of[island] if self.sticks[n] == owner)
            assert 2 * mine > self.board.degree(island), f"過半数なしの支配: 島{island}"
        for island in range(len(self.board.islands)):
            for player in Player:
                mine = sum(1 for n in self.board.lines_of[island] if self.sticks[n] == player)
                has_majority = 2 * mine > self.board.degree(island)
                if has_majority and not self.over:
                    assert self.stones[island] == player, f"支配の取りこぼし: 島{island}"
        assert UNKNOWN_CARD not in in_play


def play_game(
    choosers: tuple[Chooser, Chooser],
    rng: random.Random,
    ruleset: Ruleset | None = None,
    think_budget_sec: float = 10.0,
    on_move: Callable[[Game], None] | None = None,
) -> GameResult:
    """1ゲームを完走させる。先手(プレイヤー0)は choosers[0]。"""
    ruleset = ruleset or Ruleset()
    game = Game(rng, ruleset=ruleset)
    rules = KahunaRules(game.board, ruleset)
    side = 0
    turns = 0
    final_turns_left = 0
    while not game.over:
        turns += 1
        game.turns = turns
        if turns > MAX_TURNS:
            raise RuntimeError(f"{MAX_TURNS}手番を超えても終わらない(無限ループの疑い)")
        for _ in range(MAX_MOVES_PER_TURN):
            view = game.view(side)
            legal = rules.legal_moves(view)
            if not legal:
                raise RuntimeError(f"合法手が無い: side={side} {view}")
            move = choosers[side].choose(view, legal, TimeBudget(think_budget_sec))
            turn_over = game.apply(side, move, rules)
            game.check_invariants()
            if on_move is not None:
                on_move(game)
            if game.over or turn_over:
                break
        else:
            raise RuntimeError(f"1手番が{MAX_MOVES_PER_TURN}手を超えた")
        if game.over:
            break

        if final_turns_left:
            final_turns_left -= 1
            if final_turns_left == 0:
                game.final_scoring()
                break
        elif game.cards_left == 0:
            if game.round < 3:
                game.settle_round()
            else:
                final_turns_left = 2  # 各プレイヤーがもう1手番ずつ
        side = 1 - side

    return GameResult(
        winner=game.winner,
        scores=(game.scores[0], game.scores[1]),
        round3_points=(game.round3_points[0], game.round3_points[1]),
        turns=turns,
        early_end=game.early_end,
    )
