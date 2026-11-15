"""盤の各マスに止まる頻度を、トークン 1 個の移動の乱数シミュレーションで求める(戦略の検討用)。

ルール(ご指示と盤のキャプチャーによる。.steering/20261101-phase-monopoly/RULES.md):
- 2 個のサイコロの合計で進む。ゾロ目は、もう一度振る(3 回続けたら刑務所。標準ルールの仮定)
- [30] GO TO JAIL に止まると刑務所へ。刑務所では、ゾロ目が出たら M50 を払って出て、出た目だけ進む
  (続けて振れない)。出なければ 3 回目の後に M50 を払って JUST VISITING(10)に出る
- カードは一覧の枚数の山から、毎回ランダムに引く(山の減り方は無視した近似)。移動のカードだけ反映する
  (お金の増減と「釈放カード」は、止まる頻度に影響しないので無視)

使い方:
    uv run python -m scripts.monopoly.landing_frequency --turns 2000000
出力: マスごとの頻度(着地 1 回あたり)と、同色グループごとの稼ぎ(完成して家 3 軒のとき)。
"""

import argparse
import random

from bglm.plugins.monopoly.logic.board import (
    BOARD,
    JAIL_POSITION,
    RAILROADS,
    UTILITIES,
    SquareKind,
    next_position,
)
from bglm.plugins.monopoly.logic.catalogue import CATALOGUE
from bglm.plugins.monopoly.logic.models import DeedKind

# 移動を伴うカードの一覧(山の 16 枚のうち)。None は移動なし
_CHANCE_MOVES: tuple[str | int | None, ...] = (
    39,  # ボードウォークへ進む
    24,  # イリノイ通りへ進む
    11,  # St. チャールズプレースへ進む
    5,  # リーディング鉄道に進む
    "railroad",  # 次の鉄道(2 枚)
    "railroad",
    "utility",  # 次の水道会社か電力会社
    "back3",  # 3 マス戻る
    0,  # GO に行く
    "jail",  # 刑務所に行く
    None,
    None,
    None,
    None,
    None,
    None,  # お金の増減と釈放カード(移動なし)
)
_CHEST_MOVES: tuple[str | int | None, ...] = (0, "jail") + (None,) * 14  # GO へ進む、刑務所へ行く


class _Token:
    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.position = 0
        self.in_jail = False
        self.jail_turns = 0
        self.counts = [0] * 40

    def _land(self, position: int, depth: int = 0) -> None:
        """position に止まった処理。カードや GO TO JAIL で動くときは、動いた先で数える。"""
        kind = BOARD[position].kind
        if kind is SquareKind.GO_TO_JAIL:
            self._send_to_jail()
            return
        if kind in (SquareKind.CHANCE, SquareKind.COMMUNITY_CHEST) and depth < 3:
            deck = _CHANCE_MOVES if kind is SquareKind.CHANCE else _CHEST_MOVES
            move = self.rng.choice(deck)
            if move is not None:
                self._card_move(position, move, depth)
                return
        self.position = position
        self.counts[position] += 1

    def _card_move(self, position: int, move: str | int, depth: int) -> None:
        if move == "jail":
            self._send_to_jail()
        elif move == "railroad":
            self._land(next_position(position, RAILROADS), depth + 1)
        elif move == "utility":
            self._land(next_position(position, UTILITIES), depth + 1)
        elif move == "back3":
            self._land((position - 3) % 40, depth + 1)
        else:
            assert isinstance(move, int)
            self._land(move, depth + 1)

    def _send_to_jail(self) -> None:
        self.position = JAIL_POSITION
        self.in_jail = True
        self.jail_turns = 0
        self.counts[JAIL_POSITION] += 1

    def play_turn(self) -> None:
        doubles = 0
        while True:
            d1, d2 = self.rng.randint(1, 6), self.rng.randint(1, 6)
            if self.in_jail:
                if d1 == d2:  # 罰金を払い、出た目だけ進む。続けて振れない
                    self.in_jail = False
                    self._land((JAIL_POSITION + d1 + d2) % 40)
                else:
                    self.jail_turns += 1
                    if self.jail_turns >= 3:  # 罰金を払い、JUST VISITING へ
                        self.in_jail = False
                        self.counts[JAIL_POSITION] += 1
                return
            if d1 == d2:
                doubles += 1
                if doubles == 3:
                    self._send_to_jail()
                    return
            self._land((self.position + d1 + d2) % 40)
            if self.in_jail or d1 != d2:
                return


def landing_frequencies(turns: int, seed: int = 0) -> list[float]:
    """着地 1 回あたりの、各マスの頻度(合計 1)。"""
    token = _Token(random.Random(seed))
    for _ in range(turns):
        token.play_turn()
    total = sum(token.counts)
    return [c / total for c in token.counts]


def group_report(freq: list[float]) -> list[tuple[str, float, int, float]]:
    """同色グループごとに (グループ名, 家3軒の賃料 × 頻度の合計, 投資額, 投資 1 あたりの稼ぎ) を返す。"""
    groups: dict[str, list[int]] = {}
    for square in BOARD:
        if square.kind is SquareKind.DEED and CATALOGUE[square.name].kind is DeedKind.STREET:
            groups.setdefault(CATALOGUE[square.name].group, []).append(square.position)
    rows = []
    for group, positions in groups.items():
        income = sum(freq[p] * CATALOGUE[BOARD[p].name].rent[3] for p in positions)
        cost = sum(
            CATALOGUE[BOARD[p].name].price + 3 * CATALOGUE[BOARD[p].name].house_cost
            for p in positions
        )
        rows.append((group, income, cost, income / cost))
    return sorted(rows, key=lambda r: -r[3])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--turns", type=int, default=2_000_000)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    freq = landing_frequencies(args.turns, args.seed)
    print("マスごとの頻度(着地 1 回あたり。均等なら 0.025):")
    for square in BOARD:
        print(f"  {square.position:2d} {square.name:<24} {freq[square.position]:.4f}")
    print("\n同色グループ(完成・家 3 軒)の稼ぎ。値は 着地 1 回あたりの期待賃料 / 投資額:")
    for group, income, cost, ratio in group_report(freq):
        print(f"  {group:<11} 期待賃料 {income:6.2f}  投資 {cost:5d}  稼ぎ/投資 {ratio * 1000:.3f}")


if __name__ == "__main__":
    main()
