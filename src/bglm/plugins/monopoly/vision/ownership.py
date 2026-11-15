"""土地の詳細画面(MANAGE PROPERTY)の所有者の判定と、全体盤・拡大盤・詳細画面の座標。

座標は原寸(2432x1080)。COORDINATES.md の「色グループの拡大盤の位置」「案内消去後の拡大盤での位置」に従う。
所有者は、所有の箱の色で判定する(青 = 自分、黄 = AI、空 = 無所有)。読めない画面では推測せず、None を返す。
画面の移動は `navigation`、読み取りの手順は `holdings` が行う。
"""

from datetime import datetime
from enum import StrEnum

import numpy as np
from numpy.typing import NDArray

from bglm.core.models import Frame, Point

HELP_DISMISS = Point(1200, 540)  # 拡大盤の案内「Drag left or right...」を消す
ZOOM_RETURN = Point(330, 425)  # 拡大盤から盤へ戻る(Return)
DETAIL_RETURN_MORTGAGE = Point(1022, 933)  # 詳細画面の Return(Mortgage がある = 自分の土地)
DETAIL_RETURN_PLAIN = Point(1243, 929)  # 詳細画面の Return(Mortgage が無い)

# 詳細画面の所有の箱の中の、判定に使う点(原寸)。実機の画像で、青・黄・空を確かめた値
OWNER_BOX = (930, 448, 950, 462)
# 詳細画面の見出し(赤い帯)。MANAGE PROPERTY の画面かを確かめる
TITLE_BAR = (800, 150, 1100, 165)


class Owner(StrEnum):
    ME = "me"  # 自分(Top Hat。青い帽子)
    AI = "ai"  # AI(Dog。黄色の犬)
    NONE = "none"  # 無所有


# 全体盤で、色グループを押す位置(原寸)。鉄道は個別の位置
ZOOM_ENTRY: dict[str, Point] = {
    "brown": Point(1540, 800),
    "light_blue": Point(965, 800),
    "pink": Point(890, 717),
    "orange": Point(946, 439),
    "red": Point(1027, 293),
    "yellow": Point(1308, 293),
    "green": Point(1560, 312),
    "dark_blue": Point(1575, 601),
    "railroad_reading": Point(1249, 809),
    "railroad_pennsylvania": Point(930, 494),
    "railroad_bo": Point(1251, 300),
    "railroad_short_line": Point(1560, 495),
}

# 案内を消した後の拡大盤で、土地を押す位置(原寸)。名前 → 位置
ZOOM_TILE: dict[str, Point] = {
    "Mediterranean Avenue": Point(1437, 614),
    "Baltic Avenue": Point(1057, 614),
    "Connecticut Avenue": Point(963, 640),
    "Vermont Avenue": Point(1152, 640),
    "Oriental Avenue": Point(1534, 640),
    "Virginia Avenue": Point(957, 614),
    "States Avenue": Point(1151, 614),
    "Electric Company": Point(1337, 614),
    "St. Charles Place": Point(1529, 614),
    "St. James Place": Point(1534, 614),
    "Tennessee Avenue": Point(1151, 614),
    "New York Avenue": Point(971, 614),
    "Kentucky Avenue": Point(1529, 614),
    "Indiana Avenue": Point(1151, 614),
    "Illinois Avenue": Point(957, 614),
    "Atlantic Avenue": Point(1534, 614),
    "Ventnor Avenue": Point(1343, 614),
    "Marvin Gardens": Point(957, 614),
    "Water Works": Point(1151, 614),
    "Pacific Avenue": Point(1534, 614),
    "North Carolina Avenue": Point(1337, 614),
    "Pennsylvania Avenue": Point(957, 614),
    "Boardwalk": Point(1057, 614),
    "Park Place": Point(1437, 614),
    "Reading Railroad": Point(1257, 629),
    "Pennsylvania Railroad": Point(1257, 620),
    "B. & O. Railroad": Point(1257, 620),
    "B&O Railroad": Point(1257, 620),  # カタログ(logic)の名前
    "Short Line": Point(1257, 620),
}

# 土地 → 押す全体盤の色グループ
PROPERTY_GROUP: dict[str, str] = {
    "Mediterranean Avenue": "brown",
    "Baltic Avenue": "brown",
    "Connecticut Avenue": "light_blue",
    "Vermont Avenue": "light_blue",
    "Oriental Avenue": "light_blue",
    "Virginia Avenue": "pink",
    "States Avenue": "pink",
    "Electric Company": "pink",
    "St. Charles Place": "pink",
    "St. James Place": "orange",
    "Tennessee Avenue": "orange",
    "New York Avenue": "orange",
    "Kentucky Avenue": "red",
    "Indiana Avenue": "red",
    "Illinois Avenue": "red",
    "Atlantic Avenue": "yellow",
    "Ventnor Avenue": "yellow",
    "Marvin Gardens": "yellow",
    "Water Works": "yellow",
    "Pacific Avenue": "green",
    "North Carolina Avenue": "green",
    "Pennsylvania Avenue": "green",
    "Boardwalk": "dark_blue",
    "Park Place": "dark_blue",
    "Reading Railroad": "railroad_reading",
    "Pennsylvania Railroad": "railroad_pennsylvania",
    "B. & O. Railroad": "railroad_bo",
    "B&O Railroad": "railroad_bo",
    "Short Line": "railroad_short_line",
}


def owner_from_image(image: NDArray[np.uint8]) -> Owner | None:
    """詳細画面の画像から所有者を判定する。詳細画面でなければ None。BGR の画像。"""
    x0, y0, x1, y1 = TITLE_BAR
    title = image[y0:y1, x0:x1].reshape(-1, 3).mean(axis=0)
    blue, green, red = (float(v) for v in title)
    if not (red > 130 and red > green * 2 and red > blue * 2):
        return None  # 赤い見出しが無い = MANAGE PROPERTY ではない
    x0, y0, x1, y1 = OWNER_BOX
    b, g, r = (float(v) for v in image[y0:y1, x0:x1].reshape(-1, 3).mean(axis=0))
    if b > 200 and b > r + 100 and g < 170:
        return Owner.ME  # 青(BGR で B が大きい)
    if r > 200 and g > 200 and b < 130:
        return Owner.AI  # 黄(R と G が大きく、B が小さい)
    if min(b, g, r) > 200:
        return Owner.NONE  # 空の箱(クリーム色)
    return None


def synthetic_frame(title_bgr: tuple[int, int, int], box_bgr: tuple[int, int, int]) -> Frame:
    """判定の単体テスト用の画像。実機の画像の代わりに、見出しと所有の箱の色だけを置く。"""
    image = np.full((1080, 2432, 3), 255, dtype=np.uint8)
    x0, y0, x1, y1 = TITLE_BAR
    image[y0:y1, x0:x1] = title_bgr
    x0, y0, x1, y1 = OWNER_BOX
    image[y0:y1, x0:x1] = box_bgr
    return Frame.from_image(image, datetime(2026, 11, 4))
