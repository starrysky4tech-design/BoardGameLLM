"""Log から予測した所持金と、画面の所持金の食い違いを、どう扱うか決める(画面には依存しない)。

食い違いの多くは、Log の読み落とし(OCR の誤読、カードの受け払い、家賃の行)で、所有は変わっていない。
その場合は、全体の読み直し(再同期)をせず、画面の所持金を採って続ける。所有を変える出来事
(購入・競り・取引・建設・抵当)が絡みそうなときだけ、食い違いを残して、再同期へ回す。

2026-11-05〜11-10 の実機の対局で決めた規則(実行ログ `run_game3_*.log`)を、`scripts/run_agent.py` から移した。
挙動は変えていない。
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from bglm.plugins.monopoly.logic.events import AuctionWon, LogEvent
from bglm.plugins.monopoly.logic.ledger import mismatches
from bglm.plugins.monopoly.logic.models import Player

# 所有を変える出来事の語。読めなかった行にこの語があれば、所有が変わった疑いがあるので、画面の現金を採らない
OWNERSHIP_WORDS = re.compile(r"bought|wins|won|built|hotel|mortgag|sold|trade|auction|passed", re.I)
SMALL_DIFF = 10  # 数 ₼ の差。金額の 1 桁の誤読(OCR)とみなす
ONE_SIDED_MAX = 300  # 片側だけの、少額の差。読み落としたカードの受け払いとみなす上限


@dataclass(frozen=True)
class CashVerdict:
    cash: dict[Player, int]  # 採用する所持金
    diffs: list[str]  # 残った食い違い(再同期へ回す)
    notes: list[str] = field(default_factory=list)  # 画面に合わせた理由(記録用)


def judge_cash(
    predicted: Mapping[Player, int],
    observed: Mapping[Player, int | None],
    *,
    new_events: list[LogEvent],
    unknown_lines: list[str],
    gap: bool,
    stopped: bool,
) -> CashVerdict:
    """予測と画面の現金を比べ、採る現金と、残る食い違いを返す。

    gap: Log の取りこぼしの疑い。stopped: 位置の追跡が止まった(出目の計算と Log が食い違う)。
    """
    cash = dict(predicted)
    diffs = mismatches(predicted, observed)
    notes: list[str] = []

    def delta(player: Player) -> int | None:
        """画面 − 予測。画面が読めなければ None。"""
        seen = observed[player]
        return None if seen is None else seen - predicted[player]

    def adopt(reason: str) -> None:
        nonlocal cash, diffs
        cash = {p: seen if (seen := observed[p]) is not None else cash[p] for p in cash}
        notes.append(f"現金を画面に合わせた({reason})")
        diffs = []

    # 数 ₼ の食い違いは、金額の 1 桁の誤読。画面の現金を採る(次の食い違いで、また見える)
    small = [p for p in predicted if (d := delta(p)) is not None and 0 < abs(d) <= SMALL_DIFF]
    if diffs and len(small) == len(diffs):
        adopt("数 M の差。金額の誤読とみなす")

    # 片側だけの少額の差: 銀行とのカードの受け払いの読み落とし。所有を変える行(競り、語)が無いとき
    one_sided = [p for p in predicted if (d := delta(p)) is not None and d != 0]
    if (
        diffs
        and len(one_sided) == 1
        and abs(delta(one_sided[0]) or 0) <= ONE_SIDED_MAX
        and not gap
        and not stopped
        and not any(isinstance(e, AuctionWon) for e in new_events)
        and not any(OWNERSHIP_WORDS.search(u) for u in unknown_lines)
    ):
        adopt("片側だけの少額 = 読み落としたカードの受け払いとみなす")

    # 読めない行があり、取りこぼし(gap)が無く、所有に関わる語も無い: 読めなかった家賃などが原因
    if (
        diffs
        and unknown_lines
        and not gap
        and not stopped
        and not any(OWNERSHIP_WORDS.search(u) for u in unknown_lines)
    ):
        adopt("読めない行が原因とみなす")
    elif (
        diffs
        and not gap
        and not stopped
        and (mine := delta(Player.SELF)) is not None
        and (theirs := delta(Player.AI)) is not None
        and mine == -theirs
    ):
        # 自分と相手の間の、対称な移動(家賃の行を読み落とした)。所有は変わらない
        adopt("対称な移動 = 読み落とした家賃などとみなす")

    return CashVerdict(cash=cash, diffs=diffs, notes=notes)


MAX_AUCTION_PRICE_FACTOR = 3  # (仮) 落札額が、定価のこの倍を超えるなら、逆算しない(読み違いの疑い)


def infer_unpriced_auction(
    events: list[LogEvent],
    predicted: Mapping[Player, int],
    observed: Mapping[Player, int | None],
    ledger_owned: Mapping[str, object],
    board_owner: Mapping[str, Player | None],
) -> AuctionWon | None:
    """落札の行の金額が読めなかったとき(`won … at auction` の行だけが読めた)、画面の現金の差額から金額を逆算する。

    次を全て満たすときだけ、金額つきの落札の出来事を返す(推測で埋めない):
    - 金額の無い落札が 1 つだけ(同じ土地の金額つきの行が無い)で、台帳がその土地を所有していない
    - 全体盤の読みが、落札者の所有を示している(土地の所有者が落札者と一致)
    - 落札者の現金が、予測より減っていて(差額 = 金額)、相手の現金は予測のまま
    - 金額が、定価の `MAX_AUCTION_PRICE_FACTOR` 倍以内
    実機(2026-11-10): AI の Water Works の落札の金額が読めず、AI の現金が 200 ずれて、再同期が走った。
    """
    from bglm.plugins.monopoly.logic.catalogue import CATALOGUE

    priced = {e.square for e in events if isinstance(e, AuctionWon) and e.price is not None}
    candidates = [
        e
        for e in events
        if isinstance(e, AuctionWon)
        and e.price is None
        and not e.direct
        and e.square not in priced
        and e.square not in ledger_owned
    ]
    squares = {e.square for e in candidates}
    if len(squares) != 1 or next(iter(squares)) not in CATALOGUE:
        return None
    event = candidates[0]
    seen = observed[event.winner]
    other = observed[event.winner.other()]
    if seen is None or other is None or board_owner.get(event.square) is not event.winner:
        return None
    if other != predicted[event.winner.other()]:
        return None
    price = predicted[event.winner] - seen
    if not 0 < price <= MAX_AUCTION_PRICE_FACTOR * CATALOGUE[event.square].price:
        return None
    return AuctionWon(event.winner, event.square, price, direct=False)
