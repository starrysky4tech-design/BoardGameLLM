"""Log の読み取り(vision/log_reader.py)のテスト。

ページの重ね合わせ、信頼度の扱い、開く → 読む → 閉じる、は偽の OCR と画面で確かめる(常に動く)。
実機の Log 画面と本物の OCR(RapidOCR)による読み取りは、画面が無い環境では飛ばす。
"""

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import pytest
from numpy.typing import NDArray

from bglm.core.models import Frame, HoldDrag, InputAction, Tap
from bglm.plugins.monopoly.logic import events as ev
from bglm.plugins.monopoly.logic.models import Player
from bglm.plugins.monopoly.vision import log_reader as lr
from bglm.plugins.monopoly.vision.executor import Driver

SELF, AI = Player.SELF, Player.AI
LOG = Path("datasets/eval/monopoly/log")
FLOW = Path("datasets/eval/monopoly/roll_flow")


def line(y: float, text: str, conf: float = 0.97) -> lr.OcrLine:
    return lr.OcrLine(y, conf, text)


class FakeOcr:
    """ページごとに、決めた行を返す。"""

    def __init__(self, pages: Sequence[Sequence[lr.OcrLine]]) -> None:
        self._pages = [list(p) for p in pages]
        self.calls = 0

    def read(self, image: NDArray[np.uint8]) -> list[lr.OcrLine]:
        page = self._pages[min(self.calls, len(self._pages) - 1)]
        self.calls += 1
        return page


class ScriptedIo:
    """画面の列を順に返し、入力を記録する。入力のたびに、次の画面へ進む。"""

    def __init__(self, frames: Sequence[NDArray[np.uint8]]) -> None:
        self._frames = list(frames)
        self.index = 0
        self.actions: list[InputAction] = []

    def capture(self) -> Frame:
        image = self._frames[min(self.index, len(self._frames) - 1)]
        return Frame.from_image(image, datetime(2026, 11, 5))

    def perform(self, action: InputAction) -> None:
        self.actions.append(action)
        self.index += 1


def load(directory: Path, name: str) -> NDArray[np.uint8]:
    path = directory / f"{name}.png"
    if not path.exists():
        pytest.skip(f"実機の画面が無い: {path}")
    image = cv2.imread(str(path))
    assert image is not None
    return np.asarray(image, dtype=np.uint8)


# --- 合成(常に動く) ---


def test_events_of_marks_low_confidence_as_unknown() -> None:
    page = lr.LogPage((line(212, "Top Hat rolled 5"), line(255, "Top Hat rolled 9", conf=0.5)))
    events = lr.events_of(page)
    assert events[0] == ev.DiceRolled(SELF, 5, doubles=False)
    assert isinstance(events[1], ev.UnknownLine)  # 信頼度が低い行は、読めた数字でも採らない


def test_merge_pages_removes_the_overlap() -> None:
    a, b, c, d, e = (ev.DiceRolled(SELF, n, doubles=False) for n in (3, 4, 5, 6, 7))
    newest = [c, d, e]  # 最新のページ
    older = [a, b, c]  # スクロールで遡ったページ。末尾の c が、最新ページの先頭と重なる
    assert lr.merge_pages([newest, older]) == [a, b, c, d, e]


def test_merge_pages_without_overlap_just_concatenates() -> None:
    a, b, c = (ev.DiceRolled(SELF, n, doubles=False) for n in (3, 4, 5))
    assert lr.merge_pages([[c], [a, b]]) == [a, b, c]  # 重なりが無い(取りこぼしの疑い)


def test_merge_pages_handles_empty() -> None:
    assert lr.merge_pages([]) == []
    assert lr.merge_pages([[ev.UnknownLine("x")]]) == [ev.UnknownLine("x")]


def test_read_recent_refuses_outside_the_board_and_sends_nothing() -> None:
    io = ScriptedIo([load(FLOW, "card_dialog")])
    driver = Driver(io=io, sleep=lambda _s: None)
    reading = lr.read_recent(driver, FakeOcr([[]]))
    assert reading.events == () and "通常の画面ではない" in reading.reason
    assert io.actions == []


# --- 実機の画面と本物の OCR(重いので、画面があるときだけ) ---

EXPECTED_NEWEST = [
    ev.TurnStarted(AI),
    ev.DiceRolled(AI, 4, doubles=False),
    ev.TurnStarted(SELF),
    ev.DiceRolled(SELF, 5, doubles=False),
    ev.LandedOn(SELF, "Illinois Avenue"),
    ev.RentPaid(SELF, 40, AI),
]


@pytest.fixture(scope="module")
def real_ocr() -> lr.LogOcr:
    return lr.LogOcr()


def test_real_newest_page_is_read_into_events(real_ocr: lr.LogOcr) -> None:
    image = load(LOG, "page_newest")
    events = lr.events_of(lr.LogPage(tuple(real_ocr.read(image))))
    assert events == EXPECTED_NEWEST


def test_real_pages_merge_into_one_timeline(real_ocr: lr.LogOcr) -> None:
    names = ["page_newest", "page_older1", "page_older2", "page_older3", "page_older4"]
    pages = [lr.events_of(lr.LogPage(tuple(real_ocr.read(load(LOG, n))))) for n in names]
    timeline = lr.merge_pages(pages)
    rolls = [(e.player, e.total, e.doubles) for e in timeline if isinstance(e, ev.DiceRolled)]
    # 古い → 新しい。自分の 9(Vermont)の後に、Dog の 4(ダブル)、Dog の 7、自分の 6 と 5 が続く
    assert (SELF, 9, False) in rolls
    assert (AI, 4, True) in rolls
    assert rolls[-1] == (SELF, 5, False)
    assert not any(isinstance(e, ev.UnknownLine) for e in timeline)


def test_scroll_action_is_a_held_drag_downward() -> None:
    assert isinstance(lr.SCROLL_UP, HoldDrag)
    assert lr.SCROLL_UP.end.y > lr.SCROLL_UP.start.y and lr.SCROLL_UP.hold_ms > 0
    assert lr.LOG_BUTTON == Tap(lr.LOG_BUTTON).at


# --- LogCursor(手番ごとに読み、新しい出来事だけを返す) ---


def _rolls(*totals: int) -> list[ev.LogEvent]:
    return [ev.DiceRolled(SELF, n, doubles=False) for n in totals]


def test_cursor_returns_everything_on_the_first_read() -> None:
    cursor = lr.LogCursor()
    new, gap = cursor.update(_rolls(3, 4, 5))
    assert new == _rolls(3, 4, 5) and gap is False


def test_cursor_returns_only_the_new_tail() -> None:
    cursor = lr.LogCursor()
    cursor.update(_rolls(3, 4, 5))
    new, gap = cursor.update(_rolls(4, 5, 6, 7))  # 古い 3 が消え、6 と 7 が増えた
    assert new == _rolls(6, 7) and gap is False


def test_cursor_reports_a_gap_when_nothing_overlaps() -> None:
    cursor = lr.LogCursor()
    cursor.update(_rolls(3, 4, 5))
    new, gap = cursor.update(_rolls(8, 9))  # 行が消えて、つながらない(取りこぼしの疑い)
    assert new == _rolls(8, 9) and gap is True


def test_cursor_with_no_new_lines_returns_nothing() -> None:
    cursor = lr.LogCursor()
    cursor.update(_rolls(3, 4, 5))
    new, gap = cursor.update(_rolls(3, 4, 5))
    assert new == [] and gap is False


def test_merge_never_double_counts_a_real_event_when_unknown_lines_differ() -> None:
    # 同じ行が、ページごとに別の誤読で出る。本物の出来事(出目)は、2 回数えない。
    # 不明な行どうしだけでは重ねないので、不明の行が余分に残る(不明な行は止まる理由なので、安全側)
    roll = ev.DiceRolled(AI, 6, doubles=False)
    older = [ev.TurnStarted(AI), roll, ev.UnknownLine("DoonaidAAOninrcnt")]
    newest = [roll, ev.UnknownLine("Dog paid garbled"), ev.RentPaid(AI, 20, SELF)]
    merged = lr.merge_pages([newest, older])
    assert merged.count(roll) == 1  # 出目が重なりとして 1 回に
    assert any(isinstance(e, ev.UnknownLine) for e in merged)  # 読めなかった行は、隠さない


def test_cursor_matches_unknown_lines_across_reads() -> None:
    cursor = lr.LogCursor()
    cursor.update([ev.TurnStarted(AI), ev.UnknownLine("abc")])
    new, gap = cursor.update([ev.TurnStarted(AI), ev.UnknownLine("xyz"), ev.RentPaid(AI, 5, SELF)])
    assert new == [ev.RentPaid(AI, 5, SELF)] and gap is False


def test_merge_does_not_double_count_a_line_read_differently_on_two_pages() -> None:
    # 実機で起きた誤り: 「Dog receives ₼10 from Community Chest」が、一方のページでは出来事に、他方では不明になり、
    # 重なりが外れて、2 回数えられた(現金の予測が ₼10 多くなった)
    roll4 = ev.DiceRolled(AI, 4, doubles=True)
    got10 = ev.MoneyReceived(AI, 10, "Community Chest")
    roll6 = ev.DiceRolled(AI, 6, doubles=False)
    older = [ev.TurnStarted(AI), roll4, ev.UnknownLine("garbled")]  # 同じ行が、不明に読まれた
    newest = [got10, roll6, ev.TurnStarted(SELF)]
    merged = lr.merge_pages([newest, older])
    assert merged.count(got10) == 1
    assert [type(e).__name__ for e in merged].count("MoneyReceived") == 1


def test_overlap_needs_at_least_one_real_match() -> None:
    # 不明な行どうしだけでは、重なりとみなさない(別の行が、たまたま両方不明なだけかもしれない)
    older = [ev.UnknownLine("a")]
    newest = [ev.UnknownLine("b"), ev.RentPaid(AI, 5, SELF)]
    merged = lr.merge_pages([newest, older])
    assert len(merged) == 3  # 重ねない(取りこぼしの疑いとして、そのまま連結)


# --- read_until_joined: 前回につながるまで読む ---

SCREENS = Path("datasets/eval/monopoly/screens")


def _page(*totals: int) -> list[lr.OcrLine]:
    """上から古い順の行(1 ページ)。"""
    return [line(212 + 43 * i, f"Top Hat rolled {n}") for i, n in enumerate(totals)]


def _joined_setup(pages: Sequence[Sequence[lr.OcrLine]], history: Sequence[int]):  # type: ignore[no-untyped-def]
    board = load(SCREENS, "my_turn_end_turn")
    log = load(SCREENS, "log_open")
    io = ScriptedIo([board] + [log] * 12)
    driver = Driver(io=io, sleep=lambda _s: None)
    cursor = lr.LogCursor()
    if history:
        cursor.update(_rolls(*history))
    return driver, io, FakeOcr(pages), cursor


def _scrolls(io: ScriptedIo) -> int:
    return sum(isinstance(a, HoldDrag) for a in io.actions)


def test_joined_on_the_first_page_reads_one_page_and_never_scrolls() -> None:
    driver, io, ocr, cursor = _joined_setup([_page(5, 6, 7, 8)], history=(3, 4, 5, 6, 7))
    reading = lr.read_until_joined(driver, ocr, cursor)
    assert reading.pages == 1 and ocr.calls == 1 and _scrolls(io) == 0
    new, gap = cursor.update(reading.events)
    assert new == _rolls(8) and gap is False


def test_reads_older_pages_until_they_join() -> None:
    pages = [_page(9, 10, 11, 12), _page(6, 7, 8, 9), _page(3, 4, 5, 6)]
    driver, io, ocr, cursor = _joined_setup(pages, history=(3, 4, 5, 6, 7))
    reading = lr.read_until_joined(driver, ocr, cursor)
    assert reading.pages == 3 and _scrolls(io) == 2
    new, gap = cursor.update(reading.events)
    assert new == _rolls(8, 9, 10, 11, 12) and gap is False


def test_a_two_line_overlap_is_not_enough_to_stop() -> None:
    # 前回の末尾 [6, 7] だけが一致する(MIN_JOIN = 3 未満)。次のページまで読む
    pages = [_page(6, 7, 8, 9), _page(3, 4, 5, 6)]
    driver, _io, ocr, cursor = _joined_setup(pages, history=(3, 4, 5, 6, 7))
    assert lr.read_until_joined(driver, ocr, cursor).pages == 2


def test_gives_up_at_the_page_limit_and_reports_a_gap() -> None:
    driver, _io, ocr, cursor = _joined_setup(
        [_page(10, 11, 12), _page(8, 9, 10)], history=(2, 3, 4)
    )
    reading = lr.read_until_joined(driver, ocr, cursor, max_pages=4)
    assert reading.pages == 4
    _new, gap = cursor.update(reading.events)
    assert gap is True


def test_first_read_without_history_reads_three_pages() -> None:
    pages = [_page(9, 10, 11), _page(6, 7, 8), _page(3, 4, 5), _page(2, 12, 2)]
    driver, _io, ocr, cursor = _joined_setup(pages, history=())
    assert lr.read_until_joined(driver, ocr, cursor).pages == 3


def test_read_until_joined_refuses_outside_the_board() -> None:
    io = ScriptedIo([load(FLOW, "card_dialog")])
    reading = lr.read_until_joined(
        Driver(io=io, sleep=lambda _s: None), FakeOcr([[]]), lr.LogCursor()
    )
    assert reading.events == () and io.actions == []
