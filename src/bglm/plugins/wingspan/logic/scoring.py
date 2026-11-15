"""最終得点(出典: ルールブック R p.5、アプリの終局の画面の「詳細」。RESULT.md §10)。

合計 = 鳥の点 + ボーナス + 目的 + 卵・蓄えた餌・差し込んだ札(各 1 点)。同点は残した餌の多い方、なお同点なら引き分け。
"""

from dataclasses import dataclass

from bglm.plugins.wingspan.logic.bonus import BirdOf, BonusCard, score_bonus
from bglm.plugins.wingspan.logic.models import PlayerBoard


@dataclass(frozen=True)
class ScoreBreakdown:
    birds: int
    bonus: int
    goals: int
    eggs: int
    cached: int
    tucked: int

    @property
    def total(self) -> int:
        return self.birds + self.bonus + self.goals + self.eggs + self.cached + self.tucked


def score_board(
    board: PlayerBoard,
    bird_of: BirdOf,
    bonus_of: dict[str, BonusCard],
) -> ScoreBreakdown:
    """ボーナスは手札に残っている分だけ数える(R p.11)。表に無いボーナスは 0 点(推測しない)。"""
    return ScoreBreakdown(
        birds=sum(bird_of(b.name).points for b in board.birds()),
        bonus=sum(score_bonus(bonus_of[n], board, bird_of) for n in board.bonus if n in bonus_of),
        goals=sum(board.goal_points),
        eggs=sum(b.eggs for b in board.birds()),
        cached=sum(b.cached for b in board.birds()),
        tucked=sum(b.tucked for b in board.birds()),
    )


def winner(boards: tuple[PlayerBoard, ...], totals: tuple[int, ...]) -> list[int]:
    """勝者の添字(同点の最後は共同勝利)。同点は残した餌の個数で決める(R p.5)。"""
    best = max(totals)
    tied = [i for i, t in enumerate(totals) if t == best]
    if len(tied) == 1:
        return tied
    foods = {i: sum(boards[i].food) for i in tied}
    top = max(foods.values())
    return [i for i in tied if foods[i] == top]
