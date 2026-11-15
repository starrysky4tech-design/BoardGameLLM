"""画面の固定の座標(原寸 2432x1080 の画素)。実機の全体ボードの表示(RESULT.md §2)で測った値。

縮小した画像の座標は使わない(RESULT.md §11: 縮小画像の座標を原寸に直し忘れてタップが外れた)。
画面の配置は、全体ボードの表示(3 行 × 5 列の格子)で固定。生息地の表示とは別の座標になる。
"""

from dataclasses import dataclass

from bglm.plugins.wingspan.logic.models import HABITATS, Habitat

SCREEN_W, SCREEN_H = 2432, 1080

Rect = tuple[int, int, int, int]  # x0, y0, x1, y1

# ---- 全体ボード(自分・相手とも同じ位置) ----

COLUMN_CENTERS = (595, 875, 1152, 1432, 1712)  # 5 つの枠の中心 x
ROW_CENTERS = (233, 447, 660)  # 森林、草原、湿地の中心 y(HABITATS の並び)
CARD_W, CARD_H = 280, 216  # 置かれた鳥の札の大きさ(枠より大きい)
NAME_H = 66  # 札の上端から、札名の領域の下端まで(2 行の札名も入る)

# 右下の確定、左下の取り消し(RESULT.md §2)
CONFIRM = (2312, 987)
UNDO = (162, 987)
# 左下: 全体ボード / カードトレイのプレビュー、左上: 歯車(メニュー)、顔(相手 / 自分)
MAT_BUTTON = (
    142,
    767,
)  # 生息地の表示 ⇄ 全体ボードの切り替え(トグル。押すたびに入れ替わる。RESULT.md §18)
TRAY_BUTTON = (142, 867)
GEAR = (142, 45)
OPPONENT_FACE = (1162, 45)
MY_FACE = (1270, 50)


# 右端の数(全体ボードの表示。自分・相手とも同じ位置)。キューブ、卵、餌 5 種(果実、魚、虫、ネズミ、種)
# Y は桁の中心(桁の高さは約 30 px)。X は桁の範囲で、右の枠線(x ≥ 2391)を含まない
# 卵は「置いた数 / 上限の合計」で、小さいフォント(x ≈ 2310。桁のテンプレートでは読まない)
COUNTER_X = (2318, 2380)
CUBE_ROW_Y = 495
EGG_ROW_Y = 577
FOOD_ROWS_Y = (
    637,
    694,
    751,
    808,
    865,
)  # 果実、魚、虫、ネズミ、種(画面の並び。FOODS の並びとは違う)
COUNTER_HALF_H = 22
FOOD_ORDER_ON_SCREEN = ("fruit", "fish", "invertebrate", "rodent", "seed")


def counter_rect(y_center: int) -> Rect:
    return (COUNTER_X[0], y_center - COUNTER_HALF_H, COUNTER_X[1], y_center + COUNTER_HALF_H)


EXTRA_COLUMN_X = 1912  # 鳥が 5 羽のとき、次に使う枠は 6 列目(行動の最終の枠)


def action_slot(habitat: Habitat, birds_in_row: int) -> tuple[int, int]:
    """行動を始めるために押す枠(その行の、左端の空いた枠)。"""
    x = COLUMN_CENTERS[birds_in_row] if birds_in_row < 5 else EXTRA_COLUMN_X
    return x, ROW_CENTERS[HABITATS.index(habitat)]


# 札を引く画面の大きい札と山札(実画面 291・255 で測った中心。トレイ 3 枚、山札)
DRAW_TRAY_X = (985, 1345, 1705)
DRAW_Y = 350
DRAW_DECK = (630, 450)

# 餌の選択パネルの、ダイスのボタンの段(盤の餌箱のダイスではなく、パネルの下段の絵を押す。RESULT.md §13)
# ダイスは、左端 1545・幅 464 を個数で等分した位置に並ぶ(実測: 1 個 1775、2 個 1665 / 1897、5 個 1591〜1961)。
# 順序は、盤の餌箱のダイスを上から読んだ順
PANEL_DICE_LEFT = 1545
PANEL_DICE_WIDTH = 464
PANEL_DICE_Y = 980

# 2 種の目のダイスを押すと出る小窓の選択肢(虫、種)
TWO_FACED_CHOICE = {"invertebrate": (1756, 944), "seed": (1908, 944)}


def panel_die(rank: int, count: int) -> tuple[int, int]:
    """餌の選択パネルで、盤の餌箱の上から rank 番目(0 始まり)のダイスのボタン(全部で count 個)。"""
    return round(PANEL_DICE_LEFT + PANEL_DICE_WIDTH / count * (rank + 0.5)), PANEL_DICE_Y


# 鳥のプレイの支払い(RESULT.md §16): 「変更」を押すと餌の選択に替わり、餌を 1 個ずつ押して選ぶ(空から始まる)
PAY_CHANGE = (1893, 990)
PAY_FOOD_X0 = 1688  # 画面の並び(果実、魚、虫、ネズミ、種)の 1 つ目。間隔 106.5。y ≈ 972
PAY_FOOD_DX = 106.5
PAY_FOOD_Y = 972
# 複数の生息地の札の「生息地を選んでください」: 選択肢が 2 つのとき、左と右(札の生息地の並び順)
HABITAT_CHOICE_XS = (1752, 1968)
HABITAT_CHOICE_Y = 943


def pay_food_button(food_name: str) -> tuple[int, int]:
    index = FOOD_ORDER_ON_SCREEN.index(food_name)
    return round(PAY_FOOD_X0 + PAY_FOOD_DX * index), PAY_FOOD_Y


# 初期選択(対局の開始。RESULT.md §2、§17): 鳥 5 枚と餌 5 種から 5 つ、続けてボーナス 2 枚から 1 枚
SETUP_CARD_X = (584, 894, 1198, 1490, 1800)  # 鳥カード 5 枚の中心 x(左から)
SETUP_CARD_Y = 366
SETUP_FOOD_X = (1587, 1727, 1848, 1976, 2122)  # 餌(画面の並び: 果実、魚、虫、ネズミ、種)
SETUP_FOOD_Y = 965
SETUP_BONUS_X = (982, 1377)  # ボーナスカード 2 枚の中心 x(左から)
SETUP_BONUS_Y = 450
SETUP_TITLE: Rect = (
    350,
    100,
    1800,
    190,
)  # 画面上部の題(「…キープしたいものを 5 選んでください」など)


def setup_name_rect(index: int) -> Rect:
    """初期選択の鳥カードの札名の領域(札の上端)。"""
    x = SETUP_CARD_X[index]
    return (x - 135, 200, x + 135, 275)


# 餌箱の入力(振り直し)、スキップ(確認のダイアログ)
SKIP_CONFIRM = (1075, 692)  # 「スキップ」
SKIP_DECLINE = (1360, 695)  # 「スキップしない」(実機 2026-11-14)
# 獲得の量を選ぶ能力(カッショクペリカン「魚 3 個を共通在庫から獲得」)の「全ての餌を獲得する」ボタン(実機 2026-11-14)
GAIN_ALL = (2029, 985)
SKIP_CANCEL = (1355, 692)  # 「スキップしない」
REROLL = (2100, 988)  # 餌の獲得の枠の右(残りが同じ目のとき有効。実機で確認)


def slot_center(habitat: Habitat, column: int) -> tuple[int, int]:
    return COLUMN_CENTERS[column], ROW_CENTERS[HABITATS.index(habitat)]


def card_rect(habitat: Habitat, column: int) -> Rect:
    cx, cy = slot_center(habitat, column)
    return (cx - CARD_W // 2, cy - CARD_H // 2, cx + CARD_W // 2, cy + CARD_H // 2)


def name_rect(habitat: Habitat, column: int) -> Rect:
    """札名を読む領域。札の上端の細い帯(左右の端は札の縁を避ける)。"""
    x0, y0, x1, _ = card_rect(habitat, column)
    return (x0 + 12, y0 + 6, x1 - 12, y0 + NAME_H)


# 札の下の帯の卵の枠(札の左上からの位置)。満たされた卵は黄金色、空きは白い縁の楕円(2026-11-14 に実画面で測った)
EGG_X0 = 29
EGG_DX = 21.7
EGG_Y = 189
EGG_SLOTS = 6  # 卵の上限の最大(見えた札の最大は 6)

# カードトレイ(盤の下の右。3 枚)。名前は札の左上
TRAY_CARD_W, TRAY_CARD_H = 240, 177
TRAY_X0 = (1255, 1500, 1745)
TRAY_Y0 = 808


def egg_centers(habitat: Habitat, column: int) -> list[tuple[int, int]]:
    x0, y0, _, _ = card_rect(habitat, column)
    return [(round(x0 + EGG_X0 + EGG_DX * k), y0 + EGG_Y) for k in range(EGG_SLOTS)]


def tray_rect(index: int) -> Rect:
    return (TRAY_X0[index], TRAY_Y0, TRAY_X0[index] + TRAY_CARD_W, TRAY_Y0 + TRAY_CARD_H)


def tray_name_rect(index: int) -> Rect:
    x0, y0, x1, _ = tray_rect(index)
    return (
        x0 + 4,
        y0 - 6,
        x1 - 4,
        y0 + 58,
    )  # 左右に余白を足すと OCR の欠けが減る。2 行の長い名前も入る


@dataclass(frozen=True)
class Forbidden:
    """押してはいけない領域(02_DESIGN.md「操作の安全」)。executor がタップを拒否する。"""

    name: str
    rect: Rect


# メインメニューのボタン(RESULT.md §2)。位置は中心から ±100 × ±60 の範囲を禁止とする
def _around(x: int, y: int, half_w: int = 110, half_h: int = 70) -> Rect:
    return (x - half_w, y - half_h, x + half_w, y + half_h)


FORBIDDEN_MENU: tuple[Forbidden, ...] = (
    Forbidden("オンライン", _around(750, 856)),
    Forbidden("ストア", _around(1204, 500)),
    Forbidden("保護区の記録", _around(1124, 676)),
    Forbidden("鳥", _around(1200, 856)),
    Forbidden("ニュース", _around(1486, 676)),
    Forbidden("設定", _around(1558, 856)),
    Forbidden("クレジット", _around(1560, 496)),
    Forbidden("アチーブメント", _around(1850, 856)),
    Forbidden("ストアに移動", _around(1004, 740, 140, 60)),
)
