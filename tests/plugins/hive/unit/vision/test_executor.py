"""Hive の操作の単体テスト。画面は描いた画像を使い、タップの位置と、実行後の読み直しを確かめる。"""

from datetime import datetime

from tests.plugins.hive.support.helpers import B, W, state, tops_of
from tests.plugins.hive.support.render import render

from bglm.core.models import Frame, Point, Tap
from bglm.plugins.hive.logic.models import Color, HexCoord, Kind, Move
from bglm.plugins.hive.logic.rules import HiveRules
from bglm.plugins.hive.vision.executor import HiveExecutor, _geometry
from bglm.plugins.hive.vision.grid import find_tiles, pixel_of

RULES = HiveRules()
ORIGIN = (540.0, 1200.0)  # tests.plugins.hive.support.render.render と同じ
PIXEL_TOLERANCE = 3.0  # 描いた位置と、画像から求めた中心のずれ(画素)


class FakeIo:
    """画像を返し、タップを記録する。2回目のタップの後に、画面を after に切り替える(動いた画面)。"""

    def __init__(self, before: object, after: object, switch_after_taps: int) -> None:
        self.image = before
        self._after = after
        self._switch_after = switch_after_taps
        self.taps: list[Point] = []

    def capture(self) -> Frame:
        h, w = self.image.shape[:2]  # type: ignore[attr-defined]
        return Frame(image=self.image, width=w, height=h, captured_at=datetime.now())  # type: ignore[arg-type]

    def perform(self, action: object) -> None:
        assert isinstance(action, Tap)
        self.taps.append(action.at)
        if len(self.taps) == self._switch_after:
            self.image = self._after


def _no_sleep(_: float) -> None:
    return None


def _pixel(q: int, r: int) -> Point:
    x, y = pixel_of(HexCoord(q, r), ORIGIN)
    return Point(round(x), round(y))


def test_geometry_maps_state_coordinates_to_the_drawn_pixels() -> None:
    s = state(
        [(0, 0, W, Kind.QUEEN), (1, 0, B, Kind.ANT), (1, -1, W, Kind.SPIDER)], to_move=B, turn=3
    )
    image = render(tops_of(s))
    geo = _geometry(image, s)
    assert geo is not None
    offset, origin = geo
    centres = [(t.x, t.y) for t in find_tiles(image)]
    for at_, piece in tops_of(s).items():
        x, y = pixel_of(HexCoord(at_.q + offset.q, at_.r + offset.r), (origin.x, origin.y))
        assert any(
            abs(cx - x) <= PIXEL_TOLERANCE and abs(cy - y) <= PIXEL_TOLERANCE for cx, cy in centres
        ), piece


def test_move_taps_the_piece_then_the_target_and_verifies_the_result() -> None:
    s = state(
        [(0, 0, W, Kind.QUEEN), (1, 0, B, Kind.ANT), (0, 1, B, Kind.QUEEN)], to_move=B, turn=5
    )
    move = next(m for m in RULES.legal_moves(s) if isinstance(m, Move))
    after_state = RULES.apply(s, move)
    io = FakeIo(render(tops_of(s)), render(tops_of(after_state)), switch_after_taps=2)
    result = HiveExecutor(me=Color.BLACK, sleep=_no_sleep).execute(io, s, move)
    assert result.success, result.reason
    expected = [_pixel(move.frm.q, move.frm.r), _pixel(move.to.q, move.to.r)]
    for got, want in zip(io.taps, expected, strict=True):
        assert abs(got.x - want.x) <= PIXEL_TOLERANCE and abs(got.y - want.y) <= PIXEL_TOLERANCE


def test_unchanged_screen_fails_verification() -> None:
    s = state(
        [(0, 0, W, Kind.QUEEN), (1, 0, B, Kind.ANT), (0, 1, B, Kind.QUEEN)], to_move=B, turn=5
    )
    move = next(m for m in RULES.legal_moves(s) if isinstance(m, Move))
    before = render(tops_of(s))
    io = FakeIo(before, before, switch_after_taps=99)
    result = HiveExecutor(me=Color.BLACK, sleep=_no_sleep).execute(io, s, move)
    assert not result.success
    assert result.reason == "verify_failed"


def test_pass_is_not_executed_until_confirmed() -> None:
    s = state([(0, 0, W, Kind.QUEEN)], to_move=B, turn=5)
    io = FakeIo(render(tops_of(s)), render(tops_of(s)), switch_after_taps=99)
    from bglm.plugins.hive.logic.models import Pass

    result = HiveExecutor(me=Color.BLACK, sleep=_no_sleep).execute(io, s, Pass())
    assert not result.success
    assert io.taps == []


def test_opponent_reply_after_our_move_still_verifies() -> None:
    """アプリの相手は、こちらの手の直後に応手することがある。その盤でも成功とする(実機で確かめた事象)。"""
    s = state(
        [(0, 0, W, Kind.QUEEN), (1, 0, B, Kind.ANT), (0, 1, B, Kind.QUEEN)], to_move=B, turn=5
    )
    move = next(m for m in RULES.legal_moves(s) if isinstance(m, Move))
    after_ours = RULES.apply(s, move)
    reply = RULES.legal_moves(after_ours)[0]
    after_reply = RULES.apply(after_ours, reply)
    io = FakeIo(render(tops_of(s)), render(tops_of(after_reply)), switch_after_taps=2)
    result = HiveExecutor(me=Color.BLACK, sleep=_no_sleep).execute(io, s, move)
    assert result.success, result.reason
