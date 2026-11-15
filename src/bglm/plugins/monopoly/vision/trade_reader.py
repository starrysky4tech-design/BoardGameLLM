"""取引の画面(TRADE)から、双方の提供(土地と現金)を読む。

画面の構成(実機 2026-11-08): 右の 2 つの列が、左の列 =「Top Hat offers」(自分が渡すもの)、右の列 =
「<相手> offers」(相手が渡すもの)。各列に、土地の名前と、現金(「₼49」)が行として並ぶ。
読めない行(土地名が盤に合わない、現金の形でない)があれば、全体を None にする(推測で一部だけ使わない)。
"""

import re
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from bglm.plugins.monopoly.logic.events import match_square
from bglm.plugins.monopoly.logic.models import Trade
from bglm.plugins.monopoly.vision.dialog_reader import MIN_CONF, TextOcr

# 列の読み取り枠(原寸)。見出し(offers)の下から、リストの下端まで
MY_COLUMN_BOX = (1364, 525, 1610, 830)
OPPONENT_COLUMN_BOX = (1629, 525, 1879, 830)
_CASH = re.compile(r"^[MA]{0,2}\.?\s*(\d+)$")


@dataclass(frozen=True)
class Column:
    deeds: frozenset[str]
    cash: int


def read_column(
    image: NDArray[np.uint8], box: tuple[int, int, int, int], ocr: TextOcr
) -> Column | None:
    """1 列の土地と現金。読めない行があれば None。"""
    deeds: set[str] = set()
    cash = 0
    for item in ocr.read_box(image, box):
        text = item.text.strip()
        if not text:
            continue
        if item.confidence < MIN_CONF - 0.1:
            return None
        if m := _CASH.match(text):
            cash += int(m.group(1))
            continue
        square = match_square(text)
        if square is None:
            return None
        deeds.add(square)
    return Column(frozenset(deeds), cash)


def read_trade_offer(
    image: NDArray[np.uint8], ocr: TextOcr, proposer_is_opponent: bool = True
) -> Trade | None:
    """相手が提示した取引。proposer 側 = 相手(右の列)、partner 側 = 自分(左の列)。読めなければ None。"""
    mine = read_column(image, MY_COLUMN_BOX, ocr)
    theirs = read_column(image, OPPONENT_COLUMN_BOX, ocr)
    if mine is None or theirs is None:
        return None
    if not proposer_is_opponent:
        raise ValueError("自分が提案した取引の読み取りは、未対応")
    return Trade(
        proposer_deeds=theirs.deeds,
        proposer_cash=theirs.cash,
        partner_deeds=mine.deeds,
        partner_cash=mine.cash,
    )
