"""Kahuna のルール。出典は docs/ideas/Kahuna_アプリ内ルール.md(アプリ内 RULES の要約)。

盤面の更新(置く・取り除く・支配)は、持ち主を引数に取る純粋な関数にしてある。
自分視点の Rules(KahunaRules)と、両者の手札を持つ自己対戦(simulation.py)が同じ関数を使う。
"""

from dataclasses import dataclass, replace
from itertools import combinations
from typing import Any

from bglm.plugins.kahuna.logic.models import (
    HAND_LIMIT,
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

Sticks = tuple[Player | None, ...]
Stones = tuple[Player | None, ...]


@dataclass(frozen=True)
class Ruleset:
    """アプリ内の説明と食い違う点の切り替え(docs/ideas/Kahuna_アプリ内ルール.md の末尾)。"""

    # 2・3ラウンド目に盤上の杖コマが0本になった者が負ける。アプリ内 RULES の
    # 「A TIE OR ENDING IN BETWEEN」にはあるが、ユーザーの指示は「途中終了はない。
    # 3ラウンドを戦って合計点で決める」なので、既定は False(適用しない)
    early_end_without_sticks: bool = False


# --- 盤面の更新(持ち主を引数に取る) ---------------------------------------------


def count_sticks_at(board: BoardDef, sticks: Sticks, island: int, player: Player) -> int:
    return sum(1 for line in board.lines_of[island] if sticks[line] == player)


def controls(board: BoardDef, sticks: Sticks, island: int, player: Player) -> bool:
    """島に接する点線の半分より多くに、杖コマがあれば支配する(KAHUNA STONE PLACEMENT)。"""
    return 2 * count_sticks_at(board, sticks, island, player) > board.degree(island)


def count_sticks(sticks: Sticks, player: Player) -> int:
    return sum(1 for s in sticks if s == player)


def count_stones(stones: Stones, player: Player) -> int:
    return sum(1 for s in stones if s == player)


def place_stick(
    board: BoardDef, sticks: Sticks, stones: Stones, line: int, player: Player
) -> tuple[Sticks, Stones]:
    """点線に杖コマを置き、支配を更新する。

    支配を得たら、その島に接する相手の杖コマをすべて取り除く。それで相手が隣の島の支配を
    失ったら、その島のカフナコマも取り除く(KAHUNA STONE PLACEMENT)。

    カフナコマの個数の上限は設けない。ご確認では1人10個だが、アプリは11島の支配を認める
    (実機の最終ラウンドの結果が「CONQUERED ISLANDS 0 | 11」だった)。
    """
    if sticks[line] is not None:
        raise ValueError(f"点線 {line} は空いていない")
    new_sticks = list(sticks)
    new_stones = list(stones)
    new_sticks[line] = player
    opponent = player.other
    ends = board.lines[line]
    for island in (ends.a, ends.b):
        if new_stones[island] == player or not controls(board, tuple(new_sticks), island, player):
            continue
        new_stones[island] = player
        for other_line in board.lines_of[island]:
            if new_sticks[other_line] != opponent:
                continue
            new_sticks[other_line] = None
            far = board.other_end(other_line, island)
            if new_stones[far] == opponent and not controls(
                board, tuple(new_sticks), far, opponent
            ):
                new_stones[far] = None
    return tuple(new_sticks), tuple(new_stones)


def remove_stick(
    board: BoardDef, sticks: Sticks, stones: Stones, line: int
) -> tuple[Sticks, Stones]:
    """杖コマを取り除き、持ち主が支配を失った島のカフナコマを取り除く。"""
    owner = sticks[line]
    if owner is None:
        raise ValueError(f"点線 {line} に杖コマが無い")
    new_sticks = list(sticks)
    new_stones = list(stones)
    new_sticks[line] = None
    ends = board.lines[line]
    for island in (ends.a, ends.b):
        if new_stones[island] == owner and not controls(board, tuple(new_sticks), island, owner):
            new_stones[island] = None
    return tuple(new_sticks), tuple(new_stones)


def removal_pair_matches(board: BoardDef, cards: tuple[int, int], line: int) -> bool:
    """2枚1組が、その点線が結ぶ2島の名前だけか(REMOVAL OF AN OPPONENT'S BRIDGE)。"""
    ends = board.lines[line]
    return all(card in (ends.a, ends.b) for card in cards)


# --- 決算と勝敗 ----------------------------------------------------------------


def round_points(round_no: int, stones: Stones) -> tuple[int, int]:
    """決算で各プレイヤーが得る点(プレイヤー0, プレイヤー1)。

    1ラウンド目は多い方が1点、2ラウンド目は2点、3ラウンド目は島の数の差。同数なら0点
    (IN-BETWEEN SCORE / FINAL SCORE AND END OF THE GAME)。
    """
    mine = count_stones(stones, Player.ME)
    theirs = count_stones(stones, Player.OPPONENT)
    if mine == theirs:
        return 0, 0
    value = abs(mine - theirs) if round_no == 3 else round_no
    return (value, 0) if mine > theirs else (0, value)


def decide_winner(
    scores: tuple[int, int],
    round3_points: tuple[int, int],
    sticks: Sticks,
) -> Player | None:
    """勝者。None は引き分け。合計点 → 3ラウンド目の得点 → 盤上の杖コマの数の順
    (A TIE OR ENDING IN BETWEEN)。"""
    for pair in (
        scores,
        round3_points,
        (count_sticks(sticks, Player.ME), count_sticks(sticks, Player.OPPONENT)),
    ):
        if pair[0] != pair[1]:
            return Player.ME if pair[0] > pair[1] else Player.OPPONENT
    return None


def early_end_winner(round_no: int, sticks: Sticks) -> Player | None:
    """2・3ラウンド目に杖コマが0本の者がいれば、相手が勝つ。いなければ None。"""
    if round_no < 2:
        return None
    for player in Player:
        if count_sticks(sticks, player) == 0:
            return player.other
    return None


# --- 自分視点の Rules --------------------------------------------------------------


class KahunaRules:
    def __init__(self, board: BoardDef | None = None, ruleset: Ruleset | None = None) -> None:
        self.board = board or default_board()
        self.ruleset = ruleset or Ruleset()

    def legal_moves(self, state: KahunaState) -> list[KahunaMove]:
        if state.over or state.opponent_to_move:
            return []
        moves: list[KahunaMove] = []
        known = [c for c in state.hand if c != UNKNOWN_CARD]

        if count_sticks(state.sticks, Player.ME) < STICKS_PER_PLAYER:
            for card in sorted(set(known)):
                for line in self.board.lines_of[card]:
                    if state.sticks[line] is None:
                        moves.append(PlaceStick(card, line))

        seen: set[tuple[tuple[int, int], int]] = set()
        for x, y in combinations(known, 2):  # 手札の別々の2枚
            pair = (min(x, y), max(x, y))
            for line, owner in enumerate(state.sticks):
                if (
                    owner == Player.OPPONENT
                    and removal_pair_matches(self.board, pair, line)
                    and (pair, line) not in seen
                ):
                    seen.add((pair, line))
                    moves.append(RemoveStick(pair, line))

        for card in sorted(set(known)):
            moves.append(DiscardCard(card))

        if len(state.hand) < HAND_LIMIT:  # 5枚のときは、先に捨てないと引けない
            for card in sorted({c for c in state.market if c != UNKNOWN_CARD}):
                moves.append(DrawMarket(card))
            if state.deck_count > 0:
                moves.append(DrawDeck())
        # 引くよう強いられていても、引ける札が1枚も無ければ終えられる(詰まらないように)
        can_draw_anything = state.deck_count > 0 or any(c != UNKNOWN_CARD for c in state.market)
        if not state.must_draw or not can_draw_anything:
            moves.append(PassDraw())
        return moves

    def apply(self, state: KahunaState, move: KahunaMove) -> KahunaState:
        """手を打った後の予測盤面。引いたカードは分からないので UNKNOWN_CARD で置く。"""
        if move not in self.legal_moves(state):
            raise ValueError(f"合法手ではない: {move!r}")
        return self.apply_unchecked(state, move)

    def apply_unchecked(self, state: KahunaState, move: KahunaMove) -> KahunaState:
        """合法手かの検査を省く。思考ロジックが候補を大量に評価するときに使う(合法手だけを渡すこと)。"""
        match move:
            case PlaceStick(card=card, line=line):
                sticks, stones = place_stick(
                    self.board, state.sticks, state.stones, line, Player.ME
                )
                new = replace(
                    state, sticks=sticks, stones=stones, hand=_without(state.hand, [card])
                )
            case RemoveStick(cards=cards, line=line):
                sticks, stones = remove_stick(self.board, state.sticks, state.stones, line)
                new = replace(
                    state, sticks=sticks, stones=stones, hand=_without(state.hand, list(cards))
                )
            case DiscardCard(card=card):
                new = replace(state, hand=_without(state.hand, [card]))
            case DrawMarket(card=card):
                market = _without(state.market, [card])
                deck = state.deck_count
                if deck > 0:
                    market, deck = (*market, UNKNOWN_CARD), deck - 1
                new = replace(
                    state,
                    hand=(*state.hand, card),
                    market=market,
                    deck_count=deck,
                    opponent_to_move=True,
                )
            case DrawDeck():
                new = replace(
                    state,
                    hand=(*state.hand, UNKNOWN_CARD),
                    deck_count=state.deck_count - 1,
                    opponent_to_move=True,
                )
            case PassDraw():
                new = replace(state, opponent_to_move=True)
        return self._check_early_end(new)

    def is_terminal(self, state: KahunaState) -> bool:
        return state.over

    def outcome(self, state: KahunaState) -> str | None:
        if not state.over:
            return None
        winner = state.winner
        if winner is None:
            winner = decide_winner(state.scores, state.round3_points, state.sticks)
        if winner is None:
            return "draw"
        return "win" if winner == Player.ME else "lose"

    def diff(self, predicted: KahunaState, actual: KahunaState) -> dict[str, Any]:
        """予測と実際の差異。自分の手番が終わった後は相手が動くので比べない。"""
        if predicted.opponent_to_move:
            return {}
        result: dict[str, Any] = {}
        changed = {
            line: [predicted.sticks[line], actual.sticks[line]]
            for line in range(len(predicted.sticks))
            if predicted.sticks[line] != actual.sticks[line]
        }
        if changed:
            result["sticks"] = changed
        if predicted.stones != actual.stones:
            result["stones"] = [predicted.stones, actual.stones]
        if sorted(predicted.hand) != sorted(actual.hand):
            result["hand"] = [predicted.hand, actual.hand]
        if predicted.scores != actual.scores:
            result["scores"] = [predicted.scores, actual.scores]
        return result

    def _check_early_end(self, state: KahunaState) -> KahunaState:
        if not self.ruleset.early_end_without_sticks:
            return state
        winner = early_end_winner(state.round, state.sticks)
        if winner is None:
            return state
        return replace(state, over=True, winner=winner)


def _without(cards: tuple[int, ...], remove: list[int]) -> tuple[int, ...]:
    """cards から remove の各カードを1枚ずつ取り除く。"""
    rest = list(cards)
    for card in remove:
        rest.remove(card)
    return tuple(rest)
