"""右端の数(キューブ、餌 5 種)の読み取り。位置は layout、桁は digits(テンプレート照合)。

画面の餌の並び(果実、魚、虫、ネズミ、種)を、logic の `FOODS` の並び(虫、種、魚、果実、ネズミ)に直して返す。
1 つでも読めなければ、その項目は None(既定値で埋めない)。全体ボードの表示で、何も重ならないときに読む。
"""

from dataclasses import dataclass

from bglm.plugins.wingspan.logic.models import FOODS, Food
from bglm.plugins.wingspan.vision import layout
from bglm.plugins.wingspan.vision.digits import Glyph, read_number
from bglm.plugins.wingspan.vision.mat import Image


@dataclass(frozen=True)
class Counters:
    cubes: int | None  # 残りのキューブ(= 残りの手番)
    food: tuple[int, int, int, int, int] | None  # FOODS の並び。1 つでも読めなければ None


PANEL_LEFT = 2253  # 数のパネルの左端(基準の画面)
PANEL_SEARCH = (2150, 2330)  # 左端を探す範囲(描画がずれても入る幅)
PANEL_ROW = (470, 520)  # キューブの行の帯(紙の色の列を探す)
_PAPER_MIN = 225
_PAPER_COLUMN = 0.5


def hud_shift(image: Image) -> int:
    """右の数のパネルが、基準の画面からどれだけ横にずれているか(実機: 新しい対局で −43)。測れなければ 0。

    描画が左右にずれる対局があった(左の菱形・歯車も同じだけずれる。盤本体はずれない)。パネルの紙の色の列の左端で測る。
    """
    y0, y1 = PANEL_ROW
    x0, x1 = PANEL_SEARCH
    band = image[y0:y1, x0:x1].min(axis=2)
    columns = (band >= _PAPER_MIN).mean(axis=0) >= _PAPER_COLUMN
    found = columns.nonzero()[0]
    if found.size == 0:
        return 0
    return int(found[0] + x0 - PANEL_LEFT)


def _shifted(rect: layout.Rect, dx: int) -> layout.Rect:
    x0, y0, x1, y1 = rect
    return (x0 + dx, y0, x1 + dx, y1)


def read_counters(image: Image, templates: dict[str, Glyph] | None = None) -> Counters:
    dx = hud_shift(image)
    cubes = read_number(image, _shifted(layout.counter_rect(layout.CUBE_ROW_Y), dx), templates)
    on_screen: dict[str, int | None] = {
        name: read_number(image, _shifted(layout.counter_rect(y), dx), templates)
        for name, y in zip(layout.FOOD_ORDER_ON_SCREEN, layout.FOOD_ROWS_Y, strict=True)
    }
    values = [on_screen[Food(f).value] for f in FOODS]
    if any(v is None for v in values):
        return Counters(cubes, None)
    return Counters(cubes, (values[0], values[1], values[2], values[3], values[4]))  # type: ignore[arg-type]
