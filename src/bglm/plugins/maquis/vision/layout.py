"""Maquis の画面の座標。取得画像(横向き 2432x1080)の座標で、実機 SHG11 で測った値。

出典: `.steering/20261111-phase-maquis/RESULT.md` と `datasets/raw/maquis/feasibility/`(Git管理外)の記録画面。
盤は固定で、拡大・移動は無い(設定の「拡大表示」はオフ)ので、座標は定数でよい。
"""

from bglm.toolkit.images import Box

SCREEN_SIZE = (2432, 1080)  # (幅, 高さ)

# 地点の中心(画面の丸の中心)。団員・巡回の写真はここを中心に出る
NODE_CENTER: dict[str, tuple[int, int]] = {
    "black_market_fence": (1025, 275),
    "pont_du_nord": (1342, 275),
    "radio_b": (1675, 292),
    "parade_street": (775, 408),
    "doctor": (1000, 500),
    "slums": (1237, 497),
    "black_market": (1492, 483),
    "spare_room_ne": (1747, 533),
    "radio_a": (775, 633),
    "spare_room_w": (980, 733),
    "pont_leveque": (1242, 733),
    "grocer": (1483, 700),
    "spare_room_se": (1730, 767),
    "field_w": (792, 925),
    "cafe": (1075, 942),
    "hideout": (1317, 950),
    "field_e": (1567, 950),
    "prison": (1767, 1000),
}
NODE_REF_HALF = 38  # 空き地の基準画像との照合に使う、中心から±の画素数
# カフェは、勧誘できる人の小さな写真が常に出る(2人 → 1人 → 0人と減る)ので、基準との相関では団員を判定できない。
# 団員の写真の枠(約112px四方)の上端が、飾りの写真(上端 902)より高い位置(888〜891)に出ることで判定する
CAFE_PHOTO_TOP = (888, 892)
CAFE_PHOTO_X = (1030, 1126)

# 地点の赤い「!」(帰還不可)は、中心から右下のおよそこの位置に出る
BANG_OFFSET = (79, 35)
BANG_TOLERANCE = 32

# 任務の枠(画面上部の2枚)。左端の x と、団員の写真の枠(黒い縁)・「!」・★の位置
MISSION_LEFT: dict[str, int] = {"mission_a": 877, "mission_b": 1196}
MISSION_PHOTO_X = (90, 202)  # 左端からの x(枠の外側)
MISSION_PHOTO_Y = (26, 138)
MISSION_BANG: dict[str, tuple[int, int]] = {"mission_a": (1129, 116), "mission_b": (1449, 117)}
# ★の中心。下から順に点灯する(実機で確認)。要素は上から下
MISSION_STARS: dict[str, tuple[tuple[int, int], ...]] = {
    "mission_a": ((905, 82), (905, 127)),
    "mission_b": ((1225, 36), (1225, 82), (1225, 127)),
}
STAR_LIT_BGR = (87, 175, 207)  # 点灯した★(金)。消灯は (200, 236, 246)
STAR_OFF_BGR = (200, 236, 246)

# 資材の丸。行は上から 士気(2行)・食料・薬品・資金・情報・銃器・爆薬
RESOURCE_COLS = (489, 527, 565, 603)
RESOURCE_ROWS: dict[str, tuple[int, ...]] = {
    "morale": (420, 456),  # 1行目は4つ、2行目は3つ(合計7)
    "food": (531,),
    "medicine": (626,),
    "funds": (721,),
    "intel": (816,),
    "guns": (911,),
    "explosives": (1006,),
}
MORALE_ROW_COUNTS = (4, 3)
CIRCLE_FILLED_MIN = 115  # 丸の中心の明るさ(平均)。塗り 164 以上、空 71 以下

PHASE_BOX: Box = (698, 18, 820, 140)  # 自転車(配置)・旗(行動)のアイコン
# 任務の絵の上端の細い帯(★・写真・「!」に隠れない)。任務の種類の判別に使う: 左端からの x、y
MISSION_ART_X = (60, 285)
MISSION_ART_Y = (10, 24)
AGENTS_BOX: Box = (390, 298, 474, 342)  # 「未配置 / 使える団員」の数字(N/M)

# 右の列(行動ボタン)。上から4枠、最下枠はフェイズ・ターン終了
PLACE_BTN = (2005, 547)
SLOT_Y = (547, 662, 778, 895)
END_BTN = (2005, 1017)
CONFIRM_BOX: Box = (1862, 500, 2150, 650)  # 確認ダイアログの見出し(「ターンを終了しますか?」)
CONFIRM_BACK = (2005, 900)  # ダイアログの ↩(戻る)。確定は終了ボタンと同じ位置(END_BTN)

# 画面上部のボタン
MISSION_BUTTON = {"mission_a": (1021, 83), "mission_b": (1344, 83)}
DECK_BUTTON = (1570, 83)
DECK_BACK = (453, 183)

# 終局のダイアログ(中央)。「完全版を入手」は購入に移るので押さない
END_TITLE_BOX: Box = (540, 80, 1900, 190)
END_RETRY = (1250, 458)
END_MAIN_MENU = (1250, 620)
END_FORBIDDEN = (1250, 783)  # 完全版を入手(押してはいけない)

# 山札の画面。カード1枚の幅 446、絵は枠の左端から +95〜+215
DECK_CARD_PITCH = 446
DECK_FIRST_LEFT = (578, 595)  # 山札の最初のカードの左枠の x の範囲
DISCARD_FIRST_LEFT = (1255, 1275)  # 捨札の最初のカードの左枠の x の範囲
CARD_ICON_X = (95, 215)
CARD_ICON_Y = ((505, 590), (635, 740), (775, 870))
