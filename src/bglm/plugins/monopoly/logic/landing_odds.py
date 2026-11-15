"""相手が次の 1 手番で、各マスに止まる確率(画面には依存しない)。

建設の判断(`policies.py`)に使う。相手の現在位置が分かっていて、家を建てた直後に相手が動く、という場面で、
「その土地に止まって、家の賃料を払う確率」を出す。`landing_table.py`(長期の頻度)とは別で、現在位置からの
次の 1 手番だけを、ダブルの振り直しを含めて数える。

ルール(`.steering/20261101-phase-monopoly/RULES.md`、実機で確認した規則):
- 2 つのダイスを振って進む。ゾロ目なら、止まったマスの処理の後、もう一度振る。3 回続けてゾロ目なら、刑務所へ行く
  (3 回目では進まない)
- 止まったマスが Go To Jail(30)なら、刑務所へ行く(そのマスには止まらない扱い。家賃は発生しない)
- 刑務所の中では、ゾロ目で出て、その出目だけ進む(続けて振らない)。出られない失敗が 3 回目なら、保釈金を払って出て、
  その出目だけ進む

近似: Chance・Community Chest のカードによる移動は、数えない(カードのマスに止まったまま)。
止まる確率は「その手番で、そのマスに止まる回数の期待値」(ダブルの途中の着地も数える。家賃は着地ごとに発生する)。
"""

from collections import defaultdict
from dataclasses import dataclass

from bglm.plugins.monopoly.logic.board import (
    BOARD_SIZE,
    GO_TO_JAIL_POSITION,
    JAIL_MAX_FAILS,
    JAIL_POSITION,
)

MAX_DOUBLES = 3  # 3 回目のゾロ目で、刑務所へ
MAX_JAIL_FAILS = JAIL_MAX_FAILS  # 刑務所で、ゾロ目が出ない失敗の上限(3 回目で保釈金を払って出る)
_DICE = tuple((a, b) for a in range(1, 7) for b in range(1, 7))


@dataclass(frozen=True)
class LandingOdds:
    land: dict[int, float]  # マスの位置 → 次の手番で止まる回数の期待値(確率)
    jail: float  # 刑務所へ行く確率

    def at(self, position: int) -> float:
        return self.land.get(position, 0.0)


def next_turn_landing(position: int, in_jail: bool = False, jail_failed: int = 0) -> LandingOdds:
    """position にいるプレイヤーが、次の 1 手番で各マスに止まる確率。

    in_jail: 刑務所の中にいる(position は無視して、刑務所の位置から数える)。
    jail_failed: 刑務所で、ゾロ目が出なかった回数(0〜2)。2 なら、次の失敗で保釈金を払って出る。
    """
    if not 0 <= position < BOARD_SIZE:
        raise ValueError(f"位置は 0〜{BOARD_SIZE - 1}: {position}")
    if not 0 <= jail_failed < MAX_JAIL_FAILS:
        raise ValueError(f"jail_failed は 0〜{MAX_JAIL_FAILS - 1}: {jail_failed}")
    land: dict[int, float] = defaultdict(float)
    jail = 0.0
    weight = 1 / len(_DICE)

    if in_jail:
        for a, b in _DICE:
            leaves = a == b or jail_failed + 1 >= MAX_JAIL_FAILS
            if not leaves:
                continue
            target = (JAIL_POSITION + a + b) % BOARD_SIZE
            if target == GO_TO_JAIL_POSITION:
                jail += weight
            else:
                land[target] += weight
        return LandingOdds(dict(land), jail)

    frontier: dict[tuple[int, int], float] = {(position, 0): 1.0}
    for _ in range(MAX_DOUBLES):
        step: dict[tuple[int, int], float] = defaultdict(float)
        for (at, doubles), probability in frontier.items():
            for a, b in _DICE:
                share = probability * weight
                if a == b and doubles == MAX_DOUBLES - 1:
                    jail += share
                    continue
                target = (at + a + b) % BOARD_SIZE
                if target == GO_TO_JAIL_POSITION:
                    jail += share
                    continue
                land[target] += share
                if a == b:
                    step[(target, doubles + 1)] += share
        frontier = step
    return LandingOdds(dict(land), jail)
