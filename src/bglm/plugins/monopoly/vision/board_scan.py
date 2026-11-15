"""全体盤(通常の盤の画面)1 枚から、所有・抵当・家とホテルを読む。タップは要らない。

盤を真上から見た画像に直し(`board_geometry.warp`)、マスごとの領域で読む(2026-11-10、実機の画像 3 枚で確かめた):
- 所有: 盤の外側の縁に、土地ごとに 1 本の棒(青 = 自分、黄 = AI)。棒が無ければ無所有
- 抵当: マスの本体に、赤い「M」の印(スタンプ)
- 家: 色の帯に、緑・シアンの四角。左右の列では、家が重なって積み上がり、3D のため隣のマスへはみ出す。
  そのため、**マス単位では数えない**。色グループ単位で、緑の面積から軒数の見積もり(`house_units`)を出す
- ホテル: 帯の中央に、赤とピンクの立体のブロック。ピンクの面(明るい薄赤)の塊を数える

読めない・不確かな値は `None`(推測しない)。色補正(`color_is_normal` が偽)のときは、全て `None`。
家の数は見積もりで、台帳の値の書き換えには使わない。台帳と食い違うとき、その色グループを開いて確かめる合図にする
(正確な軒数は、拡大盤・建設画面から読む。`vision/holdings.py`)。
"""

from dataclasses import dataclass
from functools import cache

import cv2
import numpy as np
from numpy.typing import NDArray

from bglm.plugins.monopoly.logic.board import DEED_POSITION_OF
from bglm.plugins.monopoly.logic.catalogue import CATALOGUE, STREET_GROUPS
from bglm.plugins.monopoly.logic.models import Player
from bglm.plugins.monopoly.logic.reconcile import DeedObservation, GroupObservation
from bglm.plugins.monopoly.vision import board_geometry as geo
from bglm.plugins.monopoly.vision.cash import CashPair, read_cash
from bglm.plugins.monopoly.vision.executor import Driver
from bglm.plugins.monopoly.vision.ownership import Owner
from bglm.plugins.monopoly.vision.roll_reader import DiceSnapshot, snapshot
from bglm.plugins.monopoly.vision.screens import color_is_normal
from bglm.toolkit.components import connected_components

# 棒: 領域に占める、青・黄の画素の割合。所有の棒は 0.21〜0.43、棒が無いときは 0.00(実測、3 枚 84 マス)
BAR_OWNED_MIN = 0.15
BAR_EMPTY_MAX = 0.03
# 抵当の印: マスの本体の中央部に占める、赤い画素の割合。印は 0.12〜0.14(トークンで一部が隠れても 0.05)、無ければ 0.00
STAMP_MIN = 0.04
STAMP_EMPTY_MAX = 0.015
BODY_INSET = 12  # 本体の縁から、この画素数だけ内側を見る(ホテルが本体へはみ出す分を避ける)
# 家: 緑・シアンの四角(HSV。色の帯(水色 H 100、緑 V 178)と区別できる範囲)
HOUSE_H = (72, 90)
HOUSE_S_MIN = 100
HOUSE_V_MIN = 200
HOUSE_SHIFT = 18  # 家は 3D で上へ伸びる。帯の領域を、画像の上方向へこの画素数だけ広げる
# 家 1 軒あたりの面積(画素)。辺ごと(0 = 下、1 = 左、2 = 上、3 = 右)。実画像の家を数えて決めた
HOUSE_UNIT_AREA = {0: 243.0, 1: 383.0, 2: 350.0, 3: 408.0}
# ホテルのピンクの面(明るい薄赤)
HOTEL_H_MAX = 6
HOTEL_H_MIN = 165
HOTEL_S = (30, 120)
HOTEL_V_MIN = 235
HOTEL_MIN_AREA = 150  # 1 つの塊の面積の下限(ホテル 1 つは約 1000)


@dataclass(frozen=True)
class TileScan:
    owner: Owner | None  # 読めなければ None
    mortgaged: bool | None


@dataclass(frozen=True)
class GroupBuildings:
    house_units: float  # 家の軒数の見積もり(面積 ÷ 1 軒の面積)。誤差は ±1 軒ほど
    hotels: int  # ホテルの数


@dataclass(frozen=True)
class BoardScan:
    tiles: dict[str, TileScan]  # 土地の名前 → 読み取り(28 か所)
    groups: dict[str, GroupBuildings] | None  # 色グループ(街)→ 家・ホテル。読めなければ None


def _unreadable() -> BoardScan:
    return BoardScan(
        tiles={name: TileScan(None, None) for name in CATALOGUE},
        groups=None,
    )


@cache
def _street_groups() -> dict[str, tuple[int, ...]]:
    """色グループ → 街の位置。"""
    return {
        group: tuple(sorted(DEED_POSITION_OF[d.name] for d in deeds))
        for group, deeds in STREET_GROUPS.items()
    }


@cache
def _group_region(group: str) -> tuple[geo.Rect, NDArray[np.bool_]]:
    """色グループの帯(上へ HOUSE_SHIFT だけ広げた領域)の和。外接の矩形と、その中の真偽値の領域。"""
    rects = []
    for position in _street_groups()[group]:
        band = geo.tile_regions(position).band
        rects.append(geo.Rect(band.x0, max(0, band.y0 - HOUSE_SHIFT), band.x1, band.y1))
    box = geo.Rect(
        min(r.x0 for r in rects),
        min(r.y0 for r in rects),
        max(r.x1 for r in rects),
        max(r.y1 for r in rects),
    )
    mask = np.zeros((box.y1 - box.y0, box.x1 - box.x0), dtype=np.bool_)
    for r in rects:
        mask[r.y0 - box.y0 : r.y1 - box.y0, r.x0 - box.x0 : r.x1 - box.x0] = True
    return box, mask


def _owner_of_bar(blue: float, yellow: float) -> Owner | None:
    if blue >= BAR_OWNED_MIN and yellow < BAR_EMPTY_MAX:
        return Owner.ME
    if yellow >= BAR_OWNED_MIN and blue < BAR_EMPTY_MAX:
        return Owner.AI
    if blue < BAR_EMPTY_MAX and yellow < BAR_EMPTY_MAX:
        return Owner.NONE
    return None  # 中間の値、または両方の色。駒・カードが重なった疑い。推測しない


def _mortgaged(red: float) -> bool | None:
    if red >= STAMP_MIN:
        return True
    if red <= STAMP_EMPTY_MAX:
        return False
    return None


def _channels(
    hsv: NDArray[np.uint8],
) -> tuple[NDArray[np.uint8], NDArray[np.uint8], NDArray[np.uint8]]:
    return hsv[..., 0], hsv[..., 1], hsv[..., 2]


def scan_warped(warped: NDArray[np.uint8]) -> BoardScan:
    """直した画像(`board_geometry.warp` の結果)から読む。条件の計算は、必要な領域だけで行う(速さのため)。"""
    hsv = np.asarray(cv2.cvtColor(warped, cv2.COLOR_BGR2HSV), dtype=np.uint8)

    tiles: dict[str, TileScan] = {}
    for name, position in DEED_POSITION_OF.items():
        regions = geo.tile_regions(position)
        body = regions.body
        inner = geo.Rect(
            body.x0 + BODY_INSET, body.y0 + BODY_INSET, body.x1 - BODY_INSET, body.y1 - BODY_INSET
        )
        h, s, v = _channels(regions.bar.crop(hsv))
        blue = float(((h >= 95) & (h <= 125) & (s > 120) & (v > 120)).mean())
        yellow = float(((h >= 22) & (h <= 36) & (s > 150) & (v > 200)).mean())
        h, s, v = _channels(inner.crop(hsv))
        red = float((((h <= 8) | (h >= 170)) & (s > 150) & (v > 100)).mean())
        tiles[name] = TileScan(owner=_owner_of_bar(blue, yellow), mortgaged=_mortgaged(red))

    groups: dict[str, GroupBuildings] = {}
    for group, positions in _street_groups().items():
        box, mask = _group_region(group)
        h, s, v = _channels(box.crop(hsv))
        house = (h >= HOUSE_H[0]) & (h <= HOUSE_H[1]) & (s > HOUSE_S_MIN) & (v >= HOUSE_V_MIN)
        pink = (
            ((h <= HOTEL_H_MAX) | (h >= HOTEL_H_MIN))
            & (s >= HOTEL_S[0])
            & (s <= HOTEL_S[1])
            & (v >= HOTEL_V_MIN)
        )
        units = float(np.count_nonzero(house & mask)) / HOUSE_UNIT_AREA[positions[0] // 10]
        blocks, _ = connected_components((pink & mask).astype(np.uint8))
        hotels = sum(1 for c in blocks if c.area >= HOTEL_MIN_AREA)
        groups[group] = GroupBuildings(house_units=units, hotels=hotels)
    return BoardScan(tiles=tiles, groups=groups)


def scan_board(image: NDArray[np.uint8]) -> BoardScan:
    """全体盤の画像(原寸、BGR)から、28 か所の所有・抵当と、色グループの家・ホテルを読む。

    盤の通常の画面でなければ(色補正を含む)、全て読めなかった値(`None`)を返す。
    """
    if not color_is_normal(image):
        return _unreadable()
    return scan_warped(geo.warp(image))


@dataclass(frozen=True)
class BoardObservation:
    """通常の盤の画面 1 枚から読んだ全て。同じ画像から読むので、互いに食い違わない(同じ瞬間)。"""

    cash: CashPair
    board: BoardScan
    dice: DiceSnapshot | None  # 盤の上の出目(読めなければ None)

    @property
    def cash_complete(self) -> bool:
        return self.cash.me.value is not None and self.cash.ai.value is not None


def observe(image: NDArray[np.uint8]) -> BoardObservation:
    """所持金・所有・抵当・家とホテル・出目を、1 枚の画像から読む(タップなし、約 30 ms)。"""
    return BoardObservation(
        cash=read_cash(image),
        board=scan_board(image),
        dice=snapshot(image) if color_is_normal(image) else None,
    )


CASH_RETRIES = 2  # 所持金が読めなかったとき、取り直す回数(合計 CASH_RETRIES + 1 枚まで)
CASH_RETRY_SEC = 0.7  # 取り直しの間隔(数字の更新の演出が終わるまで)


def observe_with_retry(
    driver: Driver, retries: int = CASH_RETRIES, retry_sec: float = CASH_RETRY_SEC
) -> BoardObservation:
    """`observe` を行い、所持金が読めないときは、間をおいて取り直す。読めなければ、最後の読みを返す(不明のまま)。

    AI の所持金が読めない回が、3 局目の実行で 5 回あった(手番の切り替えや数字の更新の演出の間)。
    読めたときだけ採る。推測で値を埋めない。
    """
    observation = observe(driver.io.capture().image)
    for _ in range(retries):
        if observation.cash_complete:
            break
        driver.sleep(retry_sec)
        observation = observe(driver.io.capture().image)
    return observation


_PLAYER_OF = {Owner.ME: Player.SELF, Owner.AI: Player.AI, Owner.NONE: None}


def deed_observations(scan: BoardScan) -> dict[str, DeedObservation | None]:
    """全体盤の読みを、照合(`logic/reconcile.py`)の入力へ変える。所有が読めなかった土地は None。"""
    result: dict[str, DeedObservation | None] = {}
    for name, tile in scan.tiles.items():
        if tile.owner is None:
            result[name] = None
        else:
            result[name] = DeedObservation(_PLAYER_OF[tile.owner], tile.mortgaged)
    return result


def group_observations(scan: BoardScan) -> dict[str, GroupObservation] | None:
    """色グループごとの家・ホテルの見積もり。読めなければ None(家の照合を飛ばす)。"""
    if scan.groups is None:
        return None
    return {g: GroupObservation(b.house_units, b.hotels) for g, b in scan.groups.items()}
