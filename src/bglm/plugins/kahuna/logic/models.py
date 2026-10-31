"""Kahuna のデータモデル。画面にも VLM にも依存しない(docs/04 の logic の規則)。

用語は docs/06 に従う: 杖コマ(stick)=アプリ内の「bridge」、カフナコマ(stone)、点線(line)。
島・点線・プレイヤーは、盤面の定義(board.json)の並びの添字で表す。
"""

import json
from dataclasses import dataclass
from enum import IntEnum
from functools import cache
from pathlib import Path

from bglm.core.models import Point

BOARD_PATH = Path(__file__).resolve().parents[1] / "data" / "board.json"

# 個数はユーザーの確認による(2026-10-30): カード24枚、杖コマ25本×2、カフナコマ10個×2。
# ただしカフナコマは、実機で11島の支配が確認できたので、上限として扱わない
STICKS_PER_PLAYER = 25
CARD_COUNT = 24
HAND_LIMIT = 5  # アプリ内ルール GETTING STARTED / DRAWING AN ISLAND CARD
MARKET_SIZE = 3  # 同 GETTING STARTED
ROUNDS = 3
UNKNOWN_CARD = -1  # 引いたばかりで島が分からないカード(予測盤面でだけ使う)


class Player(IntEnum):
    """盤面の杖コマとカフナコマの持ち主。自分の視点では ME、相手は OPPONENT。"""

    ME = 0
    OPPONENT = 1

    @property
    def other(self) -> "Player":
        return Player(1 - self.value)


@dataclass(frozen=True)
class Line:
    a: int  # 島の添字(a < b)
    b: int
    position: Point  # 画像座標(2432x1080)。杖コマの中心(照準マークの位置とは10px前後ずれる)
    source: str  # 位置の出どころ: detected(杖コマの実測)、verified(照準マーク)、estimated(概算)

    @property
    def measured(self) -> bool:
        """実測か。False は地図からの概算。"""
        return self.source != "estimated"


@dataclass(frozen=True)
class BoardDef:
    """盤面の静的定義。ゲーム中に変わらない。"""

    islands: tuple[str, ...]
    lines: tuple[Line, ...]
    lines_of: tuple[tuple[int, ...], ...]  # 島ごとの、接する点線の添字
    stone_positions: tuple[Point, ...]  # 島ごとの、カフナコマが置かれる位置(画像座標)
    stone_measured: tuple[bool, ...]  # 島ごとに、石の位置が実測か(False は概算)

    def degree(self, island: int) -> int:
        """島に接する点線の数。支配には、この半分より多い杖コマが要る。"""
        return len(self.lines_of[island])

    def island_index(self, name: str) -> int:
        return self.islands.index(name)

    def line_between(self, a: int, b: int) -> int:
        lo, hi = min(a, b), max(a, b)
        for index, line in enumerate(self.lines):
            if (line.a, line.b) == (lo, hi):
                return index
        raise KeyError(f"点線が無い: {self.islands[a]}-{self.islands[b]}")

    def other_end(self, line: int, island: int) -> int:
        ends = self.lines[line]
        if island == ends.a:
            return ends.b
        if island == ends.b:
            return ends.a
        raise ValueError(f"点線 {line} は島 {island} に接していない")


def load_board(path: Path = BOARD_PATH) -> BoardDef:
    data = json.loads(path.read_text(encoding="utf-8"))
    islands = tuple(data["islands"])
    lines = []
    for entry in data["lines"]:
        name_a, name_b = entry["islands"]
        a, b = sorted((islands.index(name_a), islands.index(name_b)))
        lines.append(Line(a, b, Point(entry["x"], entry["y"]), entry["position"]))
    lines_of = tuple(
        tuple(i for i, line in enumerate(lines) if island in (line.a, line.b))
        for island in range(len(islands))
    )
    stones = data["stones"]
    stone_positions = tuple(Point(stones[name]["x"], stones[name]["y"]) for name in islands)
    stone_measured = tuple(stones[name]["position"] != "estimated" for name in islands)
    return BoardDef(islands, tuple(lines), lines_of, stone_positions, stone_measured)


@cache
def default_board() -> BoardDef:
    return load_board()


@dataclass(frozen=True)
class KahunaState:
    """自分の視点の盤面。相手の手札と山札の順序は見えないので持たない。"""

    sticks: tuple[Player | None, ...]  # 点線ごとの杖コマの持ち主
    stones: tuple[Player | None, ...]  # 島ごとのカフナコマの持ち主(=支配している者)
    hand: tuple[int, ...]  # 自分の手札の島の添字(UNKNOWN_CARD は未判明)
    market: tuple[int, ...]  # 場札の島の添字(UNKNOWN_CARD は未判明)
    deck_count: int
    round: int  # 1〜3
    scores: tuple[int, int]  # (自分, 相手)
    round3_points: tuple[int, int] = (0, 0)  # 3ラウンド目に得た点。同点の判定に使う
    must_draw: bool = False  # 相手が引かずに終えたため、次の手番で必ず引く
    opponent_to_move: bool = False  # 予測盤面: 自分の手番が終わった
    over: bool = False
    winner: Player | None = None  # over のとき。None は引き分け


@dataclass(frozen=True)
class PlaceStick:
    """手札の card(島)に接する空いた点線 line に杖コマを置く。"""

    card: int
    line: int


@dataclass(frozen=True)
class RemoveStick:
    """2枚1組(その点線が結ぶ2島の名前だけ)で、相手の杖コマを1本取り除く。"""

    cards: tuple[int, int]
    line: int


@dataclass(frozen=True)
class DiscardCard:
    """カードを伏せて捨てる。手札が5枚のときに引くための前提にもなる。"""

    card: int


@dataclass(frozen=True)
class DrawMarket:
    """場札から引く。手番が終わる。"""

    card: int


@dataclass(frozen=True)
class DrawDeck:
    """山札の一番上を引く。手番が終わる。"""


@dataclass(frozen=True)
class PassDraw:
    """引かずに手番を終える。相手が次に必ず引く。"""


KahunaMove = PlaceStick | RemoveStick | DiscardCard | DrawMarket | DrawDeck | PassDraw
