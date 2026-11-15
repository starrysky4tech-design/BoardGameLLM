"""Log パネルを読む(開く → 行を OCR → 出来事にする → 閉じる)。座標は原寸(2432x1080)。

Log の使い方(2026-11-05、実機で確認):
- Log ボタン (330,655) で開く。開くと、最新の行が下に出る(約 7 行が見える)
- 内容の部分を、保持してから下方向へドラッグすると、過去の行が出る。`input swipe`(保持なし)では動かない
- 閉じるのは、右上の × (1567,205)
- 各行の文字は、固定のフォント。RapidOCR で信頼度 0.93〜1.0 で読めた。誤読(I と l、₼ と M、空白の欠け)は
  logic/events.py の語彙で補正する

OCR は、1 ページ約 2 秒かかる。エンジンの読み込みは `ocr_engine` が 1 度だけ行い、`BoxOcr` と共有する。
行の重複: ページを遡ると、同じ行が複数ページに出る。行は、ページ内の並びで重ね合わせて、重複を除く。
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from bglm.core.models import HoldDrag, Point, Tap
from bglm.plugins.monopoly.logic.events import LogEvent, UnknownLine, parse_line
from bglm.plugins.monopoly.vision.executor import Driver
from bglm.toolkit.ocr_reader import recognize

LOG_BUTTON = Point(330, 655)
LOG_CLOSE = Point(1567, 205)
PANEL = (950, 205, 1545, 490)  # x0, y0, x1, y1。Log の文字の領域
OCR_SCALE = 2
MIN_CONF = 0.80  # この信頼度に満たない行は、UnknownLine にする(推測しない)
OPEN_SEC = 2.5
SCROLL_SEC = 1.5


@dataclass(frozen=True)
class OcrLine:
    y: float  # 画面上の y(原寸)
    confidence: float
    text: str


class Ocr(Protocol):
    def read(self, image: NDArray[np.uint8]) -> list[OcrLine]: ...


class LogOcr:
    """RapidOCR で Log の領域を読む。エンジンは、他の読み取りと共有する(`toolkit/ocr_reader`)。"""

    def read(self, image: NDArray[np.uint8]) -> list[OcrLine]:
        lines = [
            OcrLine(raw.y, raw.confidence, raw.text) for raw in recognize(image, PANEL, OCR_SCALE)
        ]
        return sorted(lines, key=lambda line: line.y)


@dataclass(frozen=True)
class LogPage:
    lines: tuple[OcrLine, ...]


def events_of(page: LogPage) -> list[LogEvent]:
    """1 ページの行を、上から順に出来事にする。信頼度が低い行は UnknownLine。"""
    events: list[LogEvent] = []
    for line in page.lines:
        if line.confidence < MIN_CONF:
            events.append(UnknownLine(line.text))
        else:
            events.append(parse_line(line.text))
    return events


def _compatible(a: LogEvent, b: LogEvent) -> bool:
    """重ね合わせで、2 つの行が同じ行でありうるか。

    同じ行でも、OCR の誤読がページごとに違い、一方は出来事として読め、他方は不明になる(実機で起きた)。
    不明な行は、どの行ともつながりうるとみなす。
    """
    return isinstance(a, UnknownLine) or isinstance(b, UnknownLine) or a == b


def _overlaps(first: Sequence[LogEvent], second: Sequence[LogEvent]) -> bool:
    """first と second が、同じ行の並びか。全部がつながりうる、かつ、本物の行どうしの一致が 1 つ以上ある。"""
    if len(first) != len(second) or not first:
        return False
    if not all(_compatible(a, b) for a, b in zip(first, second, strict=True)):
        return False
    return any(
        a == b and not isinstance(a, UnknownLine) for a, b in zip(first, second, strict=True)
    )


def merge_pages(newest_first: Sequence[Sequence[LogEvent]]) -> list[LogEvent]:
    """最新のページから遡った順に渡されたページを、時系列の 1 本にまとめる。

    隣り合うページは、スクロールで重なる行を持つ。新しい方のページの先頭から続く行が、古い方のページの
    末尾と一致する最長の重なりを探して、重複を除く。重なりが見つからなければ、そのまま連結する
    (行の取りこぼしがあり得るので、呼び出し側が確認する)。
    """
    if not newest_first:
        return []
    merged = list(newest_first[0])
    for older in newest_first[1:]:
        older_list = list(older)
        overlap = 0
        for k in range(min(len(older_list), len(merged)), 0, -1):
            if _overlaps(older_list[-k:], merged[:k]):
                overlap = k
                break
        merged = older_list[: len(older_list) - overlap] + merged
    return merged


# 内容を、保持してから下へドラッグして、過去の行を出す(実機で確認。保持が無い swipe では動かない)
SCROLL_UP = HoldDrag(Point(1250, 260), Point(1250, 440), hold_ms=300, steps=5, step_ms=80)


@dataclass(frozen=True)
class LogReading:
    events: tuple[LogEvent, ...]  # 時系列(古い → 新しい)
    pages: int
    reason: str = ""  # events が空のときの理由


def read_recent(driver: Driver, ocr: Ocr, pages: int = 1) -> LogReading:
    """Log を開き、最新から pages ページ分を読み、閉じる。盤の通常の画面からだけ開く。

    pages=1 は、最新の約 7 行。ダブルや Dog の複数回の Roll を含めるには、2〜3 ページ読む。
    """
    if driver.screen() not in ("board_my_turn_roll", "board_my_turn_end"):
        return LogReading((), 0, "盤の通常の画面ではない")
    driver.perform(Tap(LOG_BUTTON))
    driver.sleep(OPEN_SEC)
    if driver.screen() != "log":
        return LogReading((), 0, "Log が開かない")
    collected: list[list[LogEvent]] = []
    for index in range(pages):
        image = driver.io.capture().image
        collected.append(events_of(LogPage(tuple(ocr.read(image)))))
        if index + 1 < pages:
            driver.perform(SCROLL_UP)
            driver.sleep(SCROLL_SEC)
    driver.perform(Tap(LOG_CLOSE))
    driver.sleep(OPEN_SEC)
    return LogReading(tuple(merge_pages(collected)), len(collected))


MIN_JOIN = 3  # 前回の末尾につながった、とみなす行数の下限
MAX_PAGES = 10  # Log は約 34 行(約 5 ページ)までしか残らない。余裕を見た上限


def read_until_joined(
    driver: Driver, ocr: Ocr, cursor: "LogCursor", max_pages: int = MAX_PAGES
) -> LogReading:
    """Log を開き、前回の読みにつながるまで、最新から遡って読み、閉じる。盤の通常の画面からだけ開く。

    固定の 3 ページ(約 15 秒)ではなく、新しい出来事が少ない通常の手番では 1〜2 ページで済ませる。
    前回の読みが無ければ(初回)、3 ページ読む。上限までつながらなければ、読めた分を返す(呼び出し側が gap と判定する)。
    """
    if driver.screen() not in ("board_my_turn_roll", "board_my_turn_end"):
        return LogReading((), 0, "盤の通常の画面ではない")
    driver.perform(Tap(LOG_BUTTON))
    driver.sleep(OPEN_SEC)
    if driver.screen() != "log":
        return LogReading((), 0, "Log が開かない")
    limit = max_pages if cursor.has_history else 3
    collected: list[list[LogEvent]] = []
    timeline: list[LogEvent] = []
    for index in range(limit):
        image = driver.io.capture().image
        collected.append(events_of(LogPage(tuple(ocr.read(image)))))
        timeline = merge_pages(collected)
        if cursor.has_history and cursor.joined(timeline):
            break
        if index + 1 < limit:
            driver.perform(SCROLL_UP)
            driver.sleep(SCROLL_SEC)
    driver.perform(Tap(LOG_CLOSE))
    driver.sleep(OPEN_SEC)
    return LogReading(tuple(timeline), len(collected))


class LogCursor:
    """前回までに読んだ Log を覚え、次の読み取りで、新しい出来事だけを返す。

    Log は、約 34 行(10 ページ)までしか残らない(実機で確認)。古い行は消えるので、手番ごとに読む。
    新しい読み取りの先頭が、前回の末尾の続きになる位置を、重なりで探す。重なりが無いときは、前回と今回の
    間で行が消えた(取りこぼした)疑いがあるので、`gap=True` で知らせる。
    """

    def __init__(self) -> None:
        self._last: list[LogEvent] = []

    @property
    def has_history(self) -> bool:
        return bool(self._last)

    def _overlap_end(self, current: Sequence[LogEvent]) -> tuple[int, int]:
        """前回の末尾 k 行が、今回の先頭付近に現れる最長の重なり。(重なりの後の位置, k)。無ければ (0, 0)。"""
        for k in range(min(len(self._last), len(current)), 0, -1):
            tail = self._last[-k:]
            for start in range(0, len(current) - k + 1):
                if _overlaps(current[start : start + k], tail):
                    return start + k, k
        return 0, 0

    def joined(self, timeline: Sequence[LogEvent]) -> bool:
        """今回の読みが、前回の末尾に十分な行数でつながっているか(読み足りるか)の判定。

        前回の読みが無ければ False(全部を読む)。つながりの行数が少ないと、繰り返しの行(「… is starting its turn」)で
        たまたま合う疑いがあるので、前回の行数が少ないとき以外は MIN_JOIN 行以上を求める。
        """
        if not self._last:
            return False
        _end, k = self._overlap_end(list(timeline))
        return k >= min(MIN_JOIN, len(self._last))

    def update(self, timeline: Sequence[LogEvent]) -> tuple[list[LogEvent], bool]:
        """今回の時系列(古い → 新しい)から、新しい出来事と、取りこぼしの疑い(gap)を返す。"""
        current = list(timeline)
        if not self._last:
            self._last = current
            return current, False  # 初回は、全部を新しいとみなす(取りこぼしは判定できない)
        best, _k = self._overlap_end(current)
        new = current[best:] if best else current
        self._last = current
        return new, best == 0
