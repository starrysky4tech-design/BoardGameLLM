"""巡回カードの山札。残りを多重集合として持つ(アプリは山札を一覧で見せる。並びが引く順かは未確認)。

カードは3つの地点(①②③の順)を持つ。巡回は、①②③のうち団員も巡回もいない最初の地点に出る。
画面の地点の橙の数字は、**残りのカードのうち、巡回がその地点に出るものの枚数**(実機で確認、2026-11-11。
ターン1の開始時は①の枚数と同じ。団員を置くと、その地点を飛ばした分に再計算される)。
山札は1ターンに3枚ずつ減る。空の山札から引くときは、捨札の全部を混ぜ直す(実機で確認、ターン4)。
3地点とも団員か巡回で埋まったカードは、画面では暗い赤の数字で表示される(捕縛の印と見られる。実際の捕縛は未観測)。
"""

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

CARDS_PATH = Path(__file__).resolve().parents[1] / "data" / "patrol_cards.json"

PatrolCard = tuple[str, str, str]  # ①②③の地点 id


def landing(card: PatrolCard, occupied: frozenset[str]) -> str | None:
    """カードの巡回が出る地点: ①②③の順で、団員も巡回もいない最初の地点。

    実機で確かめた(2026-11-11): 団員のいる地点は①でも飛ばされ、巡回のいる地点も飛ばされる。
    3地点とも埋まっているときは None(その場合の捕縛の扱いは未確認)。
    """
    for at in card:
        if at not in occupied:
            return at
    return None


@dataclass(frozen=True)
class LandingCounts:
    places: dict[str, int]  # 地点 → 巡回が出るカードの残り枚数
    blocked: int  # 3地点とも埋まっていて、置き先が決まらないカードの枚数(扱いは未確認)


@dataclass(frozen=True)
class PatrolDeck:
    """山札の残り。カードの順序は持たない(同じ札は区別しない)。"""

    remaining: tuple[tuple[PatrolCard, int], ...] = ()  # (カード, 残り枚数)。カードの昇順

    @classmethod
    def of(cls, cards: Counter[PatrolCard] | list[PatrolCard]) -> "PatrolDeck":
        counts = Counter(cards)
        return cls(tuple(sorted((c, n) for c, n in counts.items() if n > 0)))

    def size(self) -> int:
        return sum(n for _, n in self.remaining)

    def drawn_from(self, card: PatrolCard, full: "PatrolDeck") -> "PatrolDeck":
        """1枚引いた後の山札。山札が空なら、捨札の全部(=`full`。そのターンに先に引いた分も含む)を混ぜ直してから引く。

        実機で確かめた(2026-11-11、4ターン目): 山札が空になった状態で次を引くと、山札が10枚に戻り、そこから1枚引かれた。
        """
        base = full if self.size() == 0 else self
        return base.without(card)

    def count(self, card: PatrolCard) -> int:
        return dict(self.remaining).get(card, 0)

    def without(self, card: PatrolCard) -> "PatrolDeck":
        """`card` が1枚引かれた後の山札。残りに無いカードは、読み取りか規則の誤りなので例外にする。"""
        counts = Counter(dict(self.remaining))
        if counts[card] <= 0:
            raise ValueError(f"山札に残っていないカードが引かれた: {card}")
        counts[card] -= 1
        return PatrolDeck.of(counts)

    def first_choice_counts(self) -> dict[str, int]:
        """地点ごとの、①がその地点である残りの枚数(ターン開始時の橙の数字)。"""
        return self.landing_counts(frozenset()).places

    def landing_counts(self, occupied: frozenset[str]) -> LandingCounts:
        """次に引くカードで、巡回が出る地点ごとの残りの枚数(画面の橙の数字)。

        `occupied` は団員か巡回のいる地点。引き方の確率は、残りの枚数に比例する(一様)。
        """
        out: Counter[str] = Counter()
        blocked = 0
        for card, n in self.remaining:
            at = landing(card, occupied)
            if at is None:
                blocked += n
            else:
                out[at] += n
        return LandingCounts(dict(out), blocked)


def load_cards(path: Path = CARDS_PATH) -> list[PatrolCard]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cards: list[PatrolCard] = []
    for entry in data["cards"]:
        if len(entry) != 3:
            raise ValueError(f"巡回カードは3地点: {entry}")
        cards.append((entry[0], entry[1], entry[2]))
    return cards


def full_deck(path: Path = CARDS_PATH) -> PatrolDeck:
    return PatrolDeck.of(load_cards(path))
