"""起動時に、28 か所の所有者と家の数を、実機から読み直す(拡大盤の下辺の棒と、上端の家)。

色グループごとに、全体盤の位置を押して、拡大盤(ライトブルーは建設画面)を開き、案内を消して、画面を読み、戻る。
同じ土地が複数の拡大盤に写る(鉄道、会社、隣の組)ので、最初に読めた値を採り、後の読みと食い違えば、その土地は
読めなかったものとして扱う。28 か所すべてが読めなければ、状態を作らない(推測で埋めない)。

読み取りは、画面の色が通常のときだけ(端末の色補正があると、棒の色が誤読される)。抵当の状態は読めない
(棒や家では分からない)ので、`Holding.mortgaged` は False のまま。呼び出し側が知っているなら上書きする。
"""

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

from bglm.core.models import Point, Tap
from bglm.plugins.monopoly.logic.catalogue import CATALOGUE, STREET_GROUPS
from bglm.plugins.monopoly.logic.models import HOTEL_LEVEL, DeedKind
from bglm.plugins.monopoly.logic.snapshot import DeedReading
from bglm.plugins.monopoly.vision import bars
from bglm.plugins.monopoly.vision import navigation as nav
from bglm.plugins.monopoly.vision.executor import Driver
from bglm.plugins.monopoly.vision.ownership import (
    DETAIL_RETURN_MORTGAGE,
    DETAIL_RETURN_PLAIN,
    ZOOM_ENTRY,
    Owner,
    owner_from_image,
)
from bglm.plugins.monopoly.vision.screens import BOARD_SCREENS, color_is_normal

# 全体盤から開く色グループ。ライトブルーは、家が建つと建設画面が開く
ZOOM_GROUPS = ("pink", "orange", "red", "yellow", "green", "dark_blue", "brown")
# カタログの名前と、Log・拡大盤での名前の違い
ALIAS = {"B. & O. Railroad": "B&O Railroad", "Short Line": "Short Line"}


@dataclass
class HoldingsResult:
    readings: dict[str, DeedReading | None] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    assumed: list[str] = field(default_factory=list)  # 読めず、呼び出し側の値で補った土地
    sources: dict[str, str] = field(
        default_factory=dict
    )  # 土地 → 読みの出どころ("own" = 自分の色グループの画面)

    @property
    def complete(self) -> bool:
        return not self.problems and all(self.readings.get(name) is not None for name in CATALOGUE)


def merge_view(
    result: HoldingsResult,
    view_name: str,
    read: dict[str, bars.PropertyReading],
    convert: Callable[[dict[str, bars.PropertyReading]], dict[str, DeedReading | None]],
) -> None:
    """1 つの表示の読み取りを、全体へ統合する。同じ土地の読みが食い違えば、その土地を読めなかったことにする。"""
    for raw_name, reading in convert(read).items():
        name = ALIAS.get(raw_name, raw_name)
        if name not in CATALOGUE:
            result.problems.append(f"{view_name}: カタログに無い土地 {raw_name}")
            continue
        own = name in CATALOGUE and (
            view_name == CATALOGUE[name].group
            or view_name == f"improvements_{CATALOGUE[name].group}"
        )
        if name in result.readings:
            before = result.readings[name]
            if own and before != reading and result.sources.get(name) != "own":
                # 隣の色グループの画面の端に写る土地は、家の数が不正確(実機: ピンクの画面の St. James Place が 0 軒)。
                # 自分の色グループの画面で読めたら、そちらを採る
                result.readings[name] = reading
                result.sources[name] = "own"
                continue
            if before != reading and not own and result.sources.get(name) == "own":
                continue  # すでに自分の色グループの画面で読めている。端の読みとの食い違いは無視する
            if before != reading:
                result.problems.append(
                    f"{name}: 表示ごとの読みが食い違う({view_name}): {before} と {reading}"
                )
                result.readings[name] = None
            continue
        result.readings[name] = reading
        if own:
            result.sources[name] = "own"


def _convert(read: dict[str, bars.PropertyReading]) -> dict[str, DeedReading | None]:
    return bars.to_deed_readings(read)


# 建設画面で、街でない土地(鉄道・会社)の位置(表示座標の x)。街の所有者は、建設画面が開いた時点で、自分と決まる
# 組に入らない土地(例: ピンクの建設画面の Pennsylvania Railroad)は、押しても反応しない。読めない土地は、
# 呼び出し側が、根拠のある値で補う(`read_all_holdings(fallback=...)`)
IMPROVEMENT_NON_STREET: dict[str, tuple[tuple[str, int], ...]] = {
    "pink": (("Electric Company", 1100),),
    "yellow": (("Water Works", 947),),
}
DETAIL_RETURN = {
    Owner.ME: DETAIL_RETURN_MORTGAGE,
    Owner.AI: DETAIL_RETURN_PLAIN,
    Owner.NONE: DETAIL_RETURN_PLAIN,
}


def _read_tile_owner(driver: Driver, x_display: int) -> tuple[Owner | None, str]:
    """建設画面の土地を押して、詳細画面の所有者を読み、閉じる。購入・抵当は押さない。"""
    driver.perform(Tap(Point(round(x_display * bars.DISPLAY_TO_FRAME), nav.IMPROVEMENT_TILE_Y)))
    driver.sleep(nav.OPEN_SEC)
    image: NDArray[np.uint8] = driver.io.capture().image
    owner = owner_from_image(image)
    if owner is None:
        return None, "詳細画面が開かない、または判定できない"
    driver.perform(Tap(DETAIL_RETURN[owner]))
    driver.sleep(nav.RETURN_SEC)
    if driver.screen() != "improvements":
        return owner, f"詳細画面を閉じた後の画面が建設画面でない: {driver.screen()}"
    return owner, ""


def _read_improvements_group(
    driver: Driver, group: str, result: HoldingsResult, image: NDArray[np.uint8]
) -> None:
    """建設画面が開いたとき(自分が組を全部持つ)の読み取り。案内を消した後の画像で、家の数を読む。"""
    houses = bars.read_buildings(image, bars.VIEWS[f"improvements_{group}"])
    read: dict[str, bars.PropertyReading] = {}
    for name, _x in bars.VIEWS[f"improvements_{group}"].tiles:
        if CATALOGUE[name].kind is DeedKind.STREET:
            read[name] = bars.PropertyReading(Owner.ME, houses[name].houses, houses[name].hotel)
    for name, x in IMPROVEMENT_NON_STREET.get(group, ()):
        owner, problem = _read_tile_owner(driver, x)
        if problem:
            result.problems.append(f"{group}/{name}: {problem}")
        read[name] = bars.PropertyReading(owner, 0, False)
    merge_view(result, f"improvements_{group}", read, _convert)


def read_all_holdings(
    driver: Driver, fallback: dict[str, DeedReading] | None = None
) -> HoldingsResult:
    """28 か所の所有と家を読む。盤の通常の画面から始める。終わったら、盤の通常の画面に戻す。

    色グループを押すと、自分がその組を全部持っていれば建設画面、そうでなければ拡大盤が開く。画面の種類で、
    読み方を変える。色の確認(端末の色補正)は、通常の盤でだけ行う(拡大盤では、探る位置が盤の地ではない)。
    """
    result = HoldingsResult()
    if driver.screen() not in BOARD_SCREENS:
        result.problems.append("盤の通常の画面ではない")
        return result
    if not color_is_normal(driver.io.capture().image):
        result.problems.append("画面の色が通常と違う(端末の色補正の疑い)")
        return result

    board_image: NDArray[np.uint8] = driver.io.capture().image
    bottom_owners = bars.read_view(board_image, bars.VIEWS["global_bottom"])

    for group in (*ZOOM_GROUPS, "light_blue"):
        opened = nav.open_group(driver, group)
        if opened.problem:
            result.problems.append(f"{group}: {opened.problem}")
        elif opened.screen == "zoomed_board" and group in bars.VIEWS:
            view = bars.read_view_full(opened.image, bars.VIEWS[group])
            merge_view(result, group, view, _convert)
        elif opened.screen == "improvements" and group == "light_blue":
            houses = bars.read_buildings(opened.image, bars.VIEWS["improvements_light_blue"])
            combined = {
                name: bars.PropertyReading(
                    bottom_owners[name], houses[name].houses, houses[name].hotel
                )
                for name in ("Connecticut Avenue", "Vermont Avenue", "Oriental Avenue")
            }
            merge_view(result, "light_blue", combined, _convert)
        elif opened.screen == "improvements" and f"improvements_{group}" in bars.VIEWS:
            _read_improvements_group(driver, group, result, opened.image)
        else:
            result.problems.append(f"{group}: 読み取りが未登録の画面: {opened.screen}")
        if not nav.return_to_board(driver):
            result.problems.append(f"{group}: 盤に戻れない")
            return result
        if not color_is_normal(driver.io.capture().image):
            result.problems.append(f"{group}: 戻った後に、画面の色が通常と違う")
            return result
    for name, reading in (fallback or {}).items():
        if result.readings.get(name) is None and name not in result.readings:
            result.readings[name] = reading
            result.assumed.append(f"{name}: 画面から読めず、呼び出し側の値で補った: {reading}")
    return result


@dataclass
class GroupHouses:
    """色グループを開いて読んだ、家の数。土地の名前 → 家の数(ホテルは 5)。読めた街だけ入る。"""

    houses: dict[str, int] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.problems


def _street_members(group: str) -> list[str]:
    return [d.name for d in STREET_GROUPS.get(group, ())]


def read_group_houses(driver: Driver, groups: tuple[str, ...]) -> GroupHouses:
    """渡された色グループだけ、拡大盤(自分の独占は建設画面)を開いて、街の家・ホテルの数を読む。

    盤の通常の画面から始め、終わったら、盤の通常の画面に戻す。軒数は、その色グループ自身の画面の読みだけを採る
    (隣の色の画面の端に写る土地は、軒数を誤る)。画面の取得は、1 つの色グループで 3 回ほど(判別と読み取りを、
    同じ取得画像で済ませる)。
    """
    result = GroupHouses()
    image, name = nav.capture(driver)
    if name not in BOARD_SCREENS:
        result.problems.append(f"盤の通常の画面ではない: {name}")
        return result
    if not color_is_normal(image):
        result.problems.append("画面の色が通常と違う(端末の色補正の疑い)")
        return result
    for group in groups:
        if group not in ZOOM_ENTRY or group not in bars.VIEWS:
            result.problems.append(f"{group}: 開く位置が未登録")
            continue
        opened = nav.open_group(driver, group, open_sec=nav.WAIT_SEC, help_sec=nav.WAIT_SEC)
        if opened.problem:
            result.problems.append(f"{group}: {opened.problem}")
        else:
            _read_group_from_image(opened.image, opened.screen, group, result)
        if not nav.return_to_board(driver, wait_sec=nav.WAIT_SEC, check_color=True):
            result.problems.append(f"{group}: 盤に戻れない、または戻った後に色が通常と違う")
            return result
    return result


def _read_group_from_image(
    image: NDArray[np.uint8], opened: str, group: str, result: GroupHouses
) -> None:
    members = _street_members(group)
    if opened == "improvements":
        view = bars.VIEWS.get(f"improvements_{group}")
        if view is None:
            result.problems.append(f"{group}: 建設画面の読み取りが未登録")
            return
        found = bars.read_buildings(image, view)
        for tile, _x in view.tiles:
            name = ALIAS.get(tile, tile)
            if name in members:
                result.houses[name] = HOTEL_LEVEL if found[tile].hotel else found[tile].houses
    else:
        read = bars.read_view_full(image, bars.VIEWS[group])
        for tile, reading in read.items():
            name = ALIAS.get(tile, tile)
            if name in members:
                result.houses[name] = HOTEL_LEVEL if reading.hotel else reading.houses
    missing = [n for n in members if n not in result.houses]
    if missing:
        result.problems.append(f"{group}: 読めなかった街 {missing}")
