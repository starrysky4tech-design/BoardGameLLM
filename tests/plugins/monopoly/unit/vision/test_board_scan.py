"""全体盤 1 枚の読み取り(vision/board_geometry.py、vision/board_scan.py)のテスト。

正解は、画像(上から見た盤の拡大)を見て手で作った(datasets/eval/monopoly/board_scan/labels.json)。
実装の出力から作っていない。評価画像は Git 管理外なので、無い環境では飛ばす。
"""

import json
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import pytest

from bglm.core.models import Frame, InputAction
from bglm.plugins.monopoly.logic.board import BOARD, SquareKind
from bglm.plugins.monopoly.logic.catalogue import CATALOGUE
from bglm.plugins.monopoly.logic.models import Player
from bglm.plugins.monopoly.vision import board_geometry as geo
from bglm.plugins.monopoly.vision import board_scan as bs
from bglm.plugins.monopoly.vision.executor import Driver
from bglm.plugins.monopoly.vision.ownership import Owner

BASE = Path("datasets/eval/monopoly/board_scan")
LABELS = BASE / "labels.json"
needs_images = pytest.mark.skipif(not LABELS.exists(), reason="評価画像が無い(Git 管理外)")


def _items() -> list[dict[str, object]]:
    return json.loads(LABELS.read_text(encoding="utf-8"))["images"] if LABELS.exists() else []


# --- 幾何 ---


def test_corner_squares_are_rejected() -> None:
    for position in (0, 10, 20, 30):
        with pytest.raises(ValueError):
            geo.tile_regions(position)


def test_every_deed_has_distinct_tile_and_bar() -> None:
    deeds = [sq.position for sq in BOARD if sq.kind is SquareKind.DEED]
    assert len(deeds) == 28
    bars = [geo.tile_regions(p).bar for p in deeds]
    assert len(set(bars)) == 28
    for position in deeds:
        regions = geo.tile_regions(position)
        assert regions.bar.area > 0 and regions.band.area > 0 and regions.body.area > 0


def test_tiles_sit_on_the_expected_sides() -> None:
    canvas_mid = geo.CANVAS // 2
    assert geo.tile_regions(1).tile.y0 > canvas_mid  # 下の行
    assert geo.tile_regions(1).tile.x0 > canvas_mid  # GO の隣(右)
    assert geo.tile_regions(11).tile.x1 < canvas_mid  # 左の列
    assert geo.tile_regions(11).tile.y0 > canvas_mid  # Jail の隣(下)
    assert geo.tile_regions(21).tile.y1 < canvas_mid  # 上の行
    assert geo.tile_regions(21).tile.x1 < canvas_mid  # Free Parking の隣(左)
    assert geo.tile_regions(31).tile.x0 > canvas_mid  # 右の列
    assert geo.tile_regions(31).tile.y1 < canvas_mid  # Go To Jail の隣(上)


def test_bar_is_outside_the_tile_and_band_is_inside() -> None:
    for position, outward in ((1, "y1"), (11, "x0"), (21, "y0"), (31, "x1")):
        regions = geo.tile_regions(position)
        tile, bar, band = regions.tile, regions.bar, regions.band
        if outward in ("y1", "x1"):
            assert getattr(bar, outward) > getattr(tile, outward)
        else:
            assert getattr(bar, outward) < getattr(tile, outward)
        assert band.x0 >= tile.x0 and band.x1 <= tile.x1
        assert band.y0 >= tile.y0 and band.y1 <= tile.y1


def test_neighbouring_tiles_do_not_overlap() -> None:
    for position in (1, 2, 11, 12, 21, 22, 31, 32):
        a, b = geo.tile_regions(position).tile, geo.tile_regions(position + 1).tile
        overlap_x = min(a.x1, b.x1) - max(a.x0, b.x0)
        overlap_y = min(a.y1, b.y1) - max(a.y0, b.y0)
        assert overlap_x <= 0 or overlap_y <= 0


# --- 判定の規則 ---


def test_owner_of_bar_rules() -> None:
    assert bs._owner_of_bar(0.30, 0.0) is Owner.ME
    assert bs._owner_of_bar(0.0, 0.30) is Owner.AI
    assert bs._owner_of_bar(0.0, 0.0) is Owner.NONE
    assert bs._owner_of_bar(0.08, 0.0) is None  # 中間: 駒・カードが重なった疑い
    assert bs._owner_of_bar(0.30, 0.30) is None  # 両方の色


def test_mortgage_thresholds() -> None:
    assert bs._mortgaged(0.12) is True
    assert bs._mortgaged(0.05) is True  # トークンで印の一部が隠れた値
    assert bs._mortgaged(0.0) is False
    assert (
        bs._mortgaged(0.01) is False
    )  # ホテルが本体へはみ出した程度(約 0.02 まで)は、内側を見るので 0 に近い
    assert bs._mortgaged(0.03) is None  # 判定できない中間


def test_abnormal_color_is_all_unreadable() -> None:
    image = np.full((1080, 2432, 3), 30, dtype=np.uint8)  # 盤の地の色ではない
    scan = bs.scan_board(image)
    assert scan.groups is None
    assert len(scan.tiles) == 28
    assert all(t.owner is None and t.mortgaged is None for t in scan.tiles.values())


# --- 実機の画像(正解は手で作った) ---


@needs_images
@pytest.mark.parametrize("item", _items(), ids=lambda i: str(i["image"]))
def test_owners_and_mortgages_match_hand_labels(item: dict[str, object]) -> None:
    scan = bs.scan_board(cv2.imread(str(BASE / str(item["image"]))))
    owners = item["owners"]
    mortgaged = item["mortgaged"]
    assert isinstance(owners, dict) and isinstance(mortgaged, list)
    assert set(owners) == set(CATALOGUE)
    for name, want in owners.items():
        got = scan.tiles[name].owner
        assert got is not None and got.value == want, f"{name}: 正解 {want}、読み {got}"
    for name, tile in scan.tiles.items():
        assert tile.mortgaged is (name in mortgaged), f"{name}: 抵当"


@needs_images
@pytest.mark.parametrize("item", _items(), ids=lambda i: str(i["image"]))
def test_buildings_match_hand_labels(item: dict[str, object]) -> None:
    scan = bs.scan_board(cv2.imread(str(BASE / str(item["image"]))))
    units = item["house_units"]
    hotels = item["hotels"]
    assert isinstance(units, dict) and isinstance(hotels, dict)
    assert scan.groups is not None
    for group, found in scan.groups.items():
        assert found.hotels == hotels.get(group, 0), f"{group}: ホテル"
        assert abs(found.house_units - units.get(group, 0)) < 0.6, f"{group}: 家の軒数の見積もり"


@needs_images
def test_scan_is_fast() -> None:
    image = cv2.imread(str(BASE / "board1.png"))
    bs.scan_board(image)
    start = time.perf_counter()
    for _ in range(5):
        bs.scan_board(image)
    assert (time.perf_counter() - start) / 5 < 0.05


# --- observe(所持金・所有・出目を同じ画像から) ---


class _FakeIo:
    def __init__(self, images: list[np.ndarray]) -> None:
        self._images = images
        self.captures = 0

    def capture(self) -> Frame:
        image = self._images[min(self.captures, len(self._images) - 1)]
        self.captures += 1
        return Frame.from_image(image, datetime(2026, 11, 10))

    def perform(self, action: InputAction) -> None:
        raise AssertionError("読み取りは入力を送らない")


@needs_images
def test_observe_reads_cash_board_and_dice_from_one_image() -> None:
    image = cv2.imread(str(BASE / "board1.png"))
    seen = bs.observe(image)
    assert seen.cash.me.value == 390 and seen.cash.ai.value == 38
    assert seen.cash_complete
    assert seen.board.tiles["Boardwalk"].owner is Owner.ME
    assert seen.dice is not None and seen.dice.values == (5, 1)  # 画像を目視(5 の目と 1 の目)


@needs_images
def test_observe_retries_until_cash_is_readable() -> None:
    good = cv2.imread(str(BASE / "board1.png"))
    blank = good.copy()
    blank[20:70, 1100:1460] = 128  # 所持金のパネルを潰す(数字が読めない)
    sleeps: list[float] = []
    io = _FakeIo([blank, blank, good])
    driver = Driver(io=io, sleep=sleeps.append)
    seen = bs.observe_with_retry(driver)
    assert seen.cash_complete and io.captures == 3 and sleeps == [bs.CASH_RETRY_SEC] * 2


@needs_images
def test_observe_gives_up_and_leaves_unknown() -> None:
    good = cv2.imread(str(BASE / "board1.png"))
    blank = good.copy()
    blank[20:70, 1100:1460] = 128
    io = _FakeIo([blank])
    seen = bs.observe_with_retry(Driver(io=io, sleep=lambda _s: None))
    assert not seen.cash_complete and io.captures == bs.CASH_RETRIES + 1
    assert seen.cash.me.value is None  # 推測で埋めない


# --- logic の入力への変換 ---


@needs_images
def test_conversion_to_reconcile_inputs() -> None:
    scan = bs.scan_board(cv2.imread(str(BASE / "board1.png")))
    deeds = bs.deed_observations(scan)
    assert deeds["Boardwalk"] == bs.DeedObservation(Player.SELF, False)
    assert deeds["Atlantic Avenue"] == bs.DeedObservation(Player.AI, True)
    assert deeds["Short Line"] == bs.DeedObservation(None, False)  # 無所有
    groups = bs.group_observations(scan)
    assert groups is not None and groups["red"].hotels == 0


def test_unreadable_board_converts_to_none() -> None:
    scan = bs.scan_board(np.full((1080, 2432, 3), 30, dtype=np.uint8))
    assert all(v is None for v in bs.deed_observations(scan).values())
    assert bs.group_observations(scan) is None
