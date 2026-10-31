"""Hive の認識の単体テスト。盤面を描いた画像で、読み取りが元の盤面に戻るかを確かめる(画面は使わない)。"""

from tests.plugins.hive.support.helpers import B, W, at, state, tops_of
from tests.plugins.hive.support.render import render

from bglm.core.models import UiKind
from bglm.plugins.hive.logic.models import Color, Kind, Place
from bglm.plugins.hive.logic.rules import HiveRules
from bglm.plugins.hive.vision.grid import find_tiles
from bglm.plugins.hive.vision.pieces import classify
from bglm.plugins.hive.vision.recognizer import HiveRecognizer, _shifted, read_board

RULES = HiveRules()


def test_read_board_returns_the_drawn_pieces() -> None:
    drawn = {
        at(0, 0): state([(0, 0, W, Kind.QUEEN)]).top(at(0, 0)),
        at(1, 0): state([(1, 0, B, Kind.ANT)]).top(at(1, 0)),
        at(0, 1): state([(0, 1, W, Kind.BEETLE)]).top(at(0, 1)),
        at(-1, 1): state([(-1, 1, B, Kind.GRASSHOPPER)]).top(at(-1, 1)),
        at(1, -1): state([(1, -1, W, Kind.SPIDER)]).top(at(1, -1)),
    }
    reading = read_board(render(drawn))
    assert reading.problems == ()
    assert reading.confidence >= 0.5
    assert _shifted(reading.tops) == _shifted(drawn)


def test_each_kind_is_read_from_its_colour() -> None:
    for kind in Kind:
        image = render({at(0, 0): state([(0, 0, B, kind)]).top(at(0, 0))})
        tiles = find_tiles(image)
        assert len(tiles) == 1
        reading = classify(tiles[0].glyph_hsv)
        assert reading.kind is kind, kind
        assert reading.confidence >= 0.5


def test_the_grid_is_found_from_tile_centres_only() -> None:
    drawn = {
        at(0, 0): state([(0, 0, W, Kind.ANT)]).top(at(0, 0)),
        at(0, 1): state([(0, 1, B, Kind.ANT)]).top(at(0, 1)),
    }
    tiles = find_tiles(render(drawn))
    assert sorted(t.side for t in tiles) == [Color.WHITE, Color.BLACK]


def test_recognizer_follows_a_legal_move() -> None:
    previous = state(
        [(0, 0, W, Kind.QUEEN), (1, 0, B, Kind.ANT)], hand={(W, Kind.SPIDER): 1}, turn=2
    )
    move = Place(Kind.SPIDER, at(0, -1))
    after = RULES.apply(previous, move)
    rec = HiveRecognizer(me=B).recognize(render(tops_of(after)), previous)
    assert rec.state is not None
    assert _shifted(tops_of(rec.state)) == _shifted(tops_of(after))
    assert rec.ui.kind is UiKind.PLAYABLE


def test_unchanged_board_keeps_the_previous_state() -> None:
    previous = state([(0, 0, W, Kind.QUEEN), (1, 0, B, Kind.ANT)], to_move=B, turn=3)
    rec = HiveRecognizer(me=B).recognize(render(tops_of(previous)), previous)
    assert rec.state == previous
    assert rec.ui.kind is UiKind.PLAYABLE


def test_board_that_no_single_move_explains_is_unknown() -> None:
    previous = state([(0, 0, W, Kind.QUEEN), (1, 0, B, Kind.ANT)], turn=3)
    impossible = {
        at(0, 0): state([(0, 0, W, Kind.QUEEN)]).top(at(0, 0)),
        at(1, 0): state([(1, 0, B, Kind.ANT)]).top(at(1, 0)),
        at(3, -1): state([(3, -1, W, Kind.ANT)]).top(at(3, -1)),
    }
    rec = HiveRecognizer(me=B).recognize(render(impossible), previous)
    assert rec.state is None
    assert rec.ui.kind is UiKind.UNKNOWN
    assert "no_matching_move" in rec.low_confidence


def test_empty_screen_is_unknown() -> None:
    rec = HiveRecognizer(me=B).recognize(render({}), state(turn=0))
    assert rec.state is None
    assert rec.ui.kind is UiKind.UNKNOWN
