"""カードトレイの 3 枚の読み取り(全体ボードの表示。盤の下の右)。

札の有無は紙の色、札名は日本語の OCR で読んで札の表と照合する(`mat` と同じ方法)。
取られた枠は空(札が無い)。表に無い札は UNKNOWN_CARD として、読んだ文字列を残す。
"""

from dataclasses import dataclass

from bglm.plugins.wingspan.logic.models import UNKNOWN_CARD, BirdCard
from bglm.plugins.wingspan.vision import layout
from bglm.plugins.wingspan.vision.layout import DRAW_Y
from bglm.plugins.wingspan.vision.mat import PAPER_MIN_FRACTION, Image, LineReader, paper_fraction
from bglm.plugins.wingspan.vision.names import match_name


@dataclass(frozen=True)
class TrayCard:
    index: int  # 左から 0〜2
    name: str  # 札の表の札名、読めなければ UNKNOWN_CARD
    text: str  # OCR の生の文字列


DRAW_CARD_MIN_PAPER = 0.30  # 札を選ぶ画面で、札の絵の上段に紙の色がこれ以上なら、選べる札(実測: 札あり 0.48〜0.82、無い 0.0〜0.02)


def draw_screen_tray(image: Image) -> tuple[str, ...]:
    """札を選ぶ画面の、3 枠の札の有無。選べる札は UNKNOWN_CARD(名前は読まない)、無い枠は空文字。"""
    return tuple(
        UNKNOWN_CARD
        if paper_fraction(image, (x - 80, DRAW_Y - 150, x + 80, DRAW_Y - 50)) >= DRAW_CARD_MIN_PAPER
        else ""
        for x in layout.DRAW_TRAY_X
    )


def read_tray(
    image: Image, read_lines: LineReader, birds: dict[str, BirdCard]
) -> list[TrayCard | None]:
    """3 つの枠を左から順に返す。札が無い(取られた)枠は None。"""
    slots: list[TrayCard | None] = []
    for index in range(3):
        if paper_fraction(image, layout.tray_rect(index)) < PAPER_MIN_FRACTION:
            slots.append(None)
            continue
        text = "".join(read_lines(image, layout.tray_name_rect(index)))
        found = match_name(text, birds)
        slots.append(TrayCard(index, found.name if found else UNKNOWN_CARD, text))
    return slots
