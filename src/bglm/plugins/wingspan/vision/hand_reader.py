"""手札の札名を、1 枚ずつタップで拡大して読む(盤を変えない操作。02_DESIGN.md「Recognizer」の入力の例外)。

実機の観測(RESULT.md §14):
- 拡大は**短いタップ**で開く。保持 250 ms の押下や、高さ 1030 では開かない(ドラッグの開始と解釈される)
- 拡大した札の位置は札ごとに違うので、広い領域を読み、札の表(鳥・ボーナス)の名前と照合する
- 拡大は、**同じ札をもう一度タップ**すると閉じる(空き地・上のバー・拡大した札の中の押下は無反応。実機で比べた)。
  別の札を押しても閉じない。**拡大前の画面との差**で閉じたかを確かめ、閉じていなければもう 1 度押す(札名の読めなさでは
  判定できない: 表に無い札は、開いていても読めない)
読めない札は UNKNOWN_CARD(推測しない)。
"""

import time
from collections.abc import Callable, Iterable

import numpy as np

from bglm.core.models import Point, Tap
from bglm.core.protocols import GameIo
from bglm.plugins.wingspan.logic.models import UNKNOWN_CARD
from bglm.plugins.wingspan.vision.hand import card_point
from bglm.plugins.wingspan.vision.mat import Image, LineReader
from bglm.plugins.wingspan.vision.names import match_name

ZOOM_REGION = (300, 330, 1250, 560)  # 拡大した札の名前が出る範囲(札ごとに位置が違うので広く取る)
DIFF_REGION = (300, 250, 1250, 800)  # 拡大の有無を見る範囲(拡大した札が覆う範囲)
OPEN_WAIT_SEC = 1.8
CLOSE_WAIT_SEC = 1.3
CLOSE_TRIES = 3
SAME_MAX = 6.0  # 拡大前との平均の画素差がこれ以下なら、閉じている(水面の揺れは数程度)


def read_zoom_name(image: Image, read_lines: LineReader, names: Iterable[str]) -> str:
    """拡大表示の札名を、表の名前に当てはめる。読めない・表に無ければ UNKNOWN_CARD。"""
    pool = list(names)
    lines = read_lines(image, ZOOM_REGION)
    # 領域に効果の文なども入るので、行ごとに照合し、最も近い 1 つを採る(全体をつなげた文字列でも試す)
    best: tuple[float, str] | None = None
    for text in [*lines, "".join(lines)]:
        found = match_name(text, pool)
        if found is not None and (best is None or found.score > best[0]):
            best = (found.score, found.name)
    return best[1] if best else UNKNOWN_CARD


def _crop(image: Image) -> np.ndarray:
    x0, y0, x1, y1 = DIFF_REGION
    return image[y0:y1, x0:x1].astype(np.int16)


def is_same_as(image: Image, baseline: Image) -> bool:
    return float(np.mean(np.abs(_crop(image) - _crop(baseline)))) <= SAME_MAX


def read_hand_names(
    io: GameIo,
    count: int,
    read_lines: LineReader,
    names: Iterable[str],
    sleep: Callable[[float], None] = time.sleep,
) -> list[str] | None:
    """手札(ボーナスを含む)count 枚の札名を、左から順に返す。拡大を閉じられなければ None(以降の入力は送らない)。"""
    pool = list(names)
    baseline = io.capture().image
    result: list[str] = []
    for index in range(count):
        x, y = card_point(count, index)
        io.perform(Tap(Point(x, y)))
        sleep(OPEN_WAIT_SEC)
        result.append(read_zoom_name(io.capture().image, read_lines, pool))
        if not _close_zoom(io, Point(x, y), baseline, sleep):
            return None
    return result


def _close_zoom(io: GameIo, card: Point, baseline: Image, sleep: Callable[[float], None]) -> bool:
    for _ in range(CLOSE_TRIES):
        io.perform(Tap(card))
        sleep(CLOSE_WAIT_SEC)
        if is_same_as(io.capture().image, baseline):
            return True
    return False
