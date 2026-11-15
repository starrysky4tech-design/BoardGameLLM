"""土地の所有者を、盤の下辺の色の棒で読む(拡大盤、または全体盤の下辺)。

棒の色: ブルー = 自分(Top Hat)、イエロー = AI(Dog)、棒なし = 無所有。家の有無では変わらない。
座標は表示画像の値(display)で登録し、判定時に原寸(2432x1080)へ 1.22 倍する。
各表示の下段の土地の中心 x は、2026-11-04 の実機の画面で確かめた値。

棒は土地ごとに 1 本ずつ、土地の列の真下にある。近い土地の中心へ割り当て、どの土地にも割り当てられない棒は無視する。
同じ土地に 2 本割り当てられたら読めなかったものとして None を返す。
"""

from collections.abc import Mapping
from dataclasses import dataclass

import cv2
import numpy as np
from numpy.typing import NDArray

from bglm.plugins.monopoly.logic.models import Player
from bglm.plugins.monopoly.logic.snapshot import DeedReading
from bglm.plugins.monopoly.vision.ownership import Owner
from bglm.toolkit.components import connected_components

DISPLAY_TO_FRAME = 1.22


@dataclass(frozen=True)
class View:
    name: str
    band: tuple[int, int]  # 棒の y の帯(原寸)
    bar_w: tuple[int, int]  # 棒の幅の範囲(原寸)
    match_px: int  # 棒の中心と土地の中心の距離の上限(原寸)
    tiles: tuple[tuple[str, int], ...]  # (土地名, 下段の中心 x の表示座標)


# 拡大盤の下段(色グループを開いたときに見える土地)。棒は約 143 画素幅。
ZOOM_BAND = (790, 860)
ZOOM_BAR_W = (110, 180)
ZOOM_MATCH_PX = 110
# 全体盤の下辺。土地の間隔が狭く、棒は約 65 画素幅。
GLOBAL_BAND = (855, 895)
GLOBAL_BAR_W = (50, 80)
GLOBAL_MATCH_PX = 45

VIEWS: dict[str, View] = {
    "pink": View(
        "pink",
        ZOOM_BAND,
        ZOOM_BAR_W,
        ZOOM_MATCH_PX,
        (
            ("St. James Place", 480),
            ("Pennsylvania Railroad", 630),
            ("Virginia Avenue", 790),
            ("States Avenue", 940),
            ("Electric Company", 1100),
            ("St. Charles Place", 1260),
        ),
    ),
    "orange": View(
        "orange",
        ZOOM_BAND,
        ZOOM_BAR_W,
        ZOOM_MATCH_PX,
        (
            ("New York Avenue", 790),
            ("Tennessee Avenue", 945),
            ("St. James Place", 1262),
            ("Pennsylvania Railroad", 1403),
            ("Virginia Avenue", 1553),
            ("States Avenue", 1708),
        ),
    ),
    "red": View(
        "red",
        ZOOM_BAND,
        ZOOM_BAR_W,
        ZOOM_MATCH_PX,
        (
            ("Ventnor Avenue", 300),
            ("Atlantic Avenue", 465),
            ("B. & O. Railroad", 630),
            ("Illinois Avenue", 790),
            ("Indiana Avenue", 945),
            ("Kentucky Avenue", 1260),
        ),
    ),
    "yellow": View(
        "yellow",
        ZOOM_BAND,
        ZOOM_BAR_W,
        ZOOM_MATCH_PX,
        (
            ("Marvin Gardens", 790),
            ("Water Works", 947),
            ("Ventnor Avenue", 1107),
            ("Atlantic Avenue", 1265),
            ("B. & O. Railroad", 1420),
            ("Illinois Avenue", 1575),
            ("Indiana Avenue", 1735),
        ),
    ),
    "green": View(
        "green",
        ZOOM_BAND,
        ZOOM_BAR_W,
        ZOOM_MATCH_PX,
        (
            ("Short Line", 630),
            ("Pennsylvania Avenue", 790),
            ("North Carolina Avenue", 1100),
            ("Pacific Avenue", 1260),
        ),
    ),
    "dark_blue": View(
        "dark_blue",
        ZOOM_BAND,
        ZOOM_BAR_W,
        ZOOM_MATCH_PX,
        (
            ("Boardwalk", 865),
            ("Park Place", 1180),
            ("Short Line", 1490),
            ("Pennsylvania Avenue", 1650),
        ),
    ),
    "brown": View(
        "brown",
        ZOOM_BAND,
        ZOOM_BAR_W,
        ZOOM_MATCH_PX,
        (
            ("Oriental Avenue", 405),
            ("Reading Railroad", 565),
            ("Baltic Avenue", 865),
            ("Mediterranean Avenue", 1180),
        ),
    ),
    # 自分がライトブルーを全部持たないとき、全体盤のライトブルーは拡大盤(建設画面でなく)で開く(実機 2026-11-08)
    "light_blue": View(
        "light_blue",
        ZOOM_BAND,
        ZOOM_BAR_W,
        ZOOM_MATCH_PX,
        (
            ("Connecticut Avenue", 795),
            ("Vermont Avenue", 950),
            ("Oriental Avenue", 1255),
            ("Reading Railroad", 1405),
            ("Baltic Avenue", 1720),
        ),
    ),
    "improvements_light_blue": View(
        "improvements_light_blue",
        ZOOM_BAND,
        ZOOM_BAR_W,
        ZOOM_MATCH_PX,
        (
            ("Connecticut Avenue", 797),
            ("Vermont Avenue", 947),
            ("Oriental Avenue", 1260),
        ),
    ),
    "improvements_pink": View(
        "improvements_pink",
        ZOOM_BAND,
        ZOOM_BAR_W,
        ZOOM_MATCH_PX,
        (
            ("Virginia Avenue", 793),
            ("States Avenue", 946),
            ("Electric Company", 1100),
            ("St. Charles Place", 1252),
        ),
    ),
    "improvements_orange": View(
        "improvements_orange",
        ZOOM_BAND,
        ZOOM_BAR_W,
        ZOOM_MATCH_PX,
        (
            ("New York Avenue", 793),
            ("Tennessee Avenue", 946),
            ("St. James Place", 1252),
        ),
    ),
    "improvements_red": View(  # 実機 2026-11-10。座標は pink と同じ配置(建設画面の土地の中心)
        "improvements_red",
        ZOOM_BAND,
        ZOOM_BAR_W,
        ZOOM_MATCH_PX,
        (
            ("Illinois Avenue", 793),
            ("Indiana Avenue", 946),
            ("Kentucky Avenue", 1252),
        ),
    ),
    "improvements_yellow": View(
        "improvements_yellow",
        ZOOM_BAND,
        ZOOM_BAR_W,
        ZOOM_MATCH_PX,
        (
            ("Marvin Gardens", 790),
            ("Water Works", 947),
            ("Ventnor Avenue", 1101),
            ("Atlantic Avenue", 1256),
        ),
    ),
    "improvements_green": View(
        "improvements_green",
        ZOOM_BAND,
        ZOOM_BAR_W,
        ZOOM_MATCH_PX,
        (
            ("Pennsylvania Avenue", 793),
            ("North Carolina Avenue", 1100),
            ("Pacific Avenue", 1252),
        ),
    ),
    "improvements_dark_blue": View(
        "improvements_dark_blue",
        ZOOM_BAND,
        ZOOM_BAR_W,
        ZOOM_MATCH_PX,
        (
            ("Boardwalk", 868),
            ("Park Place", 1174),
        ),
    ),
    "global_bottom": View(
        "global_bottom",
        GLOBAL_BAND,
        GLOBAL_BAR_W,
        GLOBAL_MATCH_PX,
        (
            ("Connecticut Avenue", 761),
            ("Vermont Avenue", 819),
            ("Oriental Avenue", 941),
            ("Reading Railroad", 999),
            ("Baltic Avenue", 1119),
            ("Mediterranean Avenue", 1240),
        ),
    ),
}


@dataclass(frozen=True)
class Bar:
    x: int  # 中心 x(原寸)
    owner: Owner


def find_bars(image: NDArray[np.uint8], view: View) -> list[Bar]:
    """帯の中の、ブルーとイエローの棒を、中心 x の順に返す。BGR の原寸画像。"""
    y0, y1 = view.band
    w_min, w_max = view.bar_w
    crop = image[y0:y1]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    blue = ((h >= 95) & (h <= 125) & (s > 120) & (v > 120)).astype(np.uint8)
    yellow = ((h >= 18) & (h <= 35) & (s > 120) & (v > 160)).astype(np.uint8)
    bars: list[Bar] = []
    for mask, owner in ((blue, Owner.ME), (yellow, Owner.AI)):
        for c in connected_components(mask)[0]:
            if w_min <= c.width <= w_max and 10 <= c.height <= 60 and c.area >= 150:
                bars.append(Bar(c.x + c.width // 2, owner))
    return sorted(bars, key=lambda b: b.x)


def read_view(image: NDArray[np.uint8], view: View) -> dict[str, Owner | None]:
    """その表示の土地の所有者。棒が無い土地は Owner.NONE。割り当てに失敗した土地は None。"""
    bars = find_bars(image, view)
    centers = {name: round(x * DISPLAY_TO_FRAME) for name, x in view.tiles}
    assigned: dict[str, list[Bar]] = {name: [] for name in centers}
    for bar in bars:
        name, dist = min(
            ((name, abs(bar.x - cx)) for name, cx in centers.items()), key=lambda t: t[1]
        )
        if dist <= view.match_px:
            assigned[name].append(bar)
    result: dict[str, Owner | None] = {}
    for name, found in assigned.items():
        if not found:
            result[name] = Owner.NONE
        elif len(found) == 1:
            result[name] = found[0].owner
        else:
            result[name] = None  # 1 つの土地に棒が 2 本:読めない
    return result


# 拡大盤で、家(緑の四角)とホテル(赤の四角)は土地の上端に並ぶ。原寸の帯と、土地の列の幅。
HOUSE_BAND = (485, 545)
HOUSE_COLUMN_HALF = 85  # 土地の中心から、左右にこの画素数までを、その土地の列とみなす
HOUSE_MIN_AREA = 800  # 1 軒の四角の面積の下限(原寸。1 軒は約 1800)


@dataclass(frozen=True)
class Buildings:
    houses: int
    hotel: bool


def _count_squares(mask: NDArray[np.uint8], x0: int, x1: int) -> int:
    return sum(
        1
        for c in connected_components(mask)[0]
        if x0 <= c.x + c.width // 2 < x1
        and c.area >= HOUSE_MIN_AREA
        and 30 <= c.width <= 60
        and 30 <= c.height <= 60
    )


def _has_wide_pale_red(mask: NDArray[np.uint8], x0: int, x1: int) -> bool:
    """ピンクの地の上のホテル: 薄赤と赤(横の面)が合わさって、土地の幅いっぱいの横長の塊(実機: 約 160×52、面積約 3200)になる。"""
    return any(
        x0 <= c.x + c.width // 2 < x1
        and 120 <= c.width <= 200
        and 35 <= c.height <= 65
        and c.area >= 2500
        for c in connected_components(mask)[0]
    )


def read_buildings(image: NDArray[np.uint8], view: View) -> dict[str, Buildings]:
    """拡大盤の土地ごとの家の数(緑)とホテル(赤)。BGR の原寸画像。"""
    y0, y1 = HOUSE_BAND
    hsv = cv2.cvtColor(image[y0:y1], cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    green = ((h >= 40) & (h <= 90) & (s > 120) & (v > 100)).astype(np.uint8)
    # ホテルは、ピンクの地の上では、明るい薄赤(H 176〜179、S 90〜190、V 255)になる。ピンクの帯(V 222)とは、明るさで分ける
    reddish = (h <= 8) | (h >= 170)
    red = (reddish & (s > 150) & (v > 100)).astype(np.uint8)
    pale_red = (reddish & (s > 85) & (v >= 240)).astype(np.uint8)
    result: dict[str, Buildings] = {}
    for name, x in view.tiles:
        cx = round(x * DISPLAY_TO_FRAME)
        x0, x1 = cx - HOUSE_COLUMN_HALF, cx + HOUSE_COLUMN_HALF
        houses = _count_squares(green, x0, x1)
        hotel = _count_squares(red, x0, x1) > 0 or (
            # 幅広の薄赤の塊は、ピンクの地の上のホテル。赤い色グループの色帯(赤)を、ホテルと誤認しないため、ピンクだけ
            view.name.endswith("pink") and _has_wide_pale_red(red | pale_red, x0, x1)
        )
        result[name] = Buildings(houses=houses, hotel=hotel)
    return result


@dataclass(frozen=True)
class PropertyReading:
    owner: Owner | None  # 読めなければ None
    houses: int
    hotel: bool


def read_view_full(image: NDArray[np.uint8], view: View) -> dict[str, PropertyReading]:
    """拡大盤 1 枚から、土地ごとの所有者と家・ホテルの数をまとめて読む。"""
    owners = read_view(image, view)
    buildings = read_buildings(image, view)
    return {
        name: PropertyReading(owners[name], buildings[name].houses, buildings[name].hotel)
        for name in owners
    }


def to_deed_readings(
    readings: Mapping[str, PropertyReading],
) -> dict[str, DeedReading | None]:
    """画面の読み取り結果を、logic の入力へ変える。所有が読めなかった土地は None(読めていない)。"""
    owner_of = {Owner.ME: Player.SELF, Owner.AI: Player.AI, Owner.NONE: None}
    converted: dict[str, DeedReading | None] = {}
    for name, reading in readings.items():
        if reading.owner is None:
            converted[name] = None
            continue
        converted[name] = DeedReading(
            owner=owner_of[reading.owner], houses=reading.houses, hotel=reading.hotel
        )
    return converted
