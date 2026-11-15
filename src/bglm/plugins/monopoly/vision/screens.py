"""Monopoly の画面の種類の判別。座標は原寸(2432x1080)。

各画面は、固定位置の小さなテンプレート(data/screens/)で判別する。テンプレートは、2026-11-01 の
実機のスクリーンショットから切り出した。テンプレートの元の位置の近傍だけを照合するので、
同じ文字が画面の別の場所にあっても取り違えない。

判別の順序は重要: Bid のキーパッドは AUCTION の上に重なって出るため、先に判定する。
どれにも当たらないときは UNKNOWN を返す(推測で別の画面にしない)。
"""

from dataclasses import dataclass
from functools import cache
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from bglm.toolkit.images import load_image
from bglm.toolkit.matching import match_score
from bglm.toolkit.screen import LANDSCAPE_SIZE, has_size

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "data" / "screens"
IMAGE_SIZE = LANDSCAPE_SIZE  # 幅, 高さ
SEARCH_MARGIN = 15  # テンプレートの元の位置の周囲を、この画素数だけ探す
MATCH_MIN = 0.90  # 正規化相関の下限。下回れば、その画面には当たらない

UNKNOWN = "unknown"
# 盤の通常の画面(自分の手番の Roll・End Turn、負債のメニュー)。操作の始点と、戻り先に使う
BOARD_SCREENS = ("board_my_turn_roll", "board_my_turn_end", "board_debt")
POST_BAIL_LABEL = (290, 400, 385, 445)  # 収監中のメニューの「Post Bail」の文字
BAIL_TOP_LABEL = (290, 350, 385, 385)  # Roll が無いメニューの「Post Bail」の文字(いちばん上)
DEBT_LABEL = (290, 250, 385, 300)  # 負債のメニューの「Auto Sell」の文字(いちばん上)
JAIL_DEBT_LABEL = (290, 340, 385, 395)  # 刑務所で保釈金に足りないときの「Auto Sell」(2 番目)
USE_CARD_LABEL = (
    290,
    350,
    385,
    388,
)  # 釈放カードを持つときのメニューの「Use Card」の文字(Roll の下)


@dataclass(frozen=True)
class Signature:
    name: str  # 判別結果の画面名
    template: str  # data/screens/ のファイル名(拡張子なし)
    home: tuple[int, int, int, int]  # 切り出した元の位置 (x0, y0, x1, y1)


# 優先順。先に書いたものを優先する(重なる画面の取り違えを防ぐ)
SIGNATURES: tuple[Signature, ...] = (
    Signature("bid_keypad", "bid_keypad", (1290, 755, 1400, 815)),
    # 「BUY PROPERTY」の見出し = 購入の確認(Yes / No)。実機 2026-11-07: 購入画面(FOR SALE)の上に重なる
    Signature("confirm_dialog", "buy_dialog", (1160, 330, 1340, 380)),
    # 「建設済みの上限」などの通知(OK だけ)。確認ダイアログの帯と形が違う(Yes / No が無い)
    Signature("ok_dialog", "ok_dialog", (1215, 815, 1300, 860)),
    Signature("jail_dialog", "jail_dialog", (1180, 330, 1320, 390)),
    # 確認ダイアログ(購入・見送り・Forfeit・取引の取り消し・建設の確定など)。下の No / Yes の帯が共通。
    # 背後に、オークションや取引の画面が透けるので、それらより先に判別する。購入画面と保釈の画面は、
    # 同じ帯を持つので、見出しで見分けられるそれらを、先に置く
    Signature("confirm_dialog", "confirm_bar", (940, 720, 1575, 866)),
    # 土地のカードが付く購入画面(実機 2026-11-07。見出しの位置が高く、ボタンの位置は同じ)。
    # 確認ダイアログが重なったとき、背後の見出しにも当たるので、確認ダイアログより後に置く
    Signature("buy_dialog", "buy_dialog_card", (1171, 152, 1342, 189)),
    Signature("auction", "auction", (1040, 66, 1200, 104)),
    Signature("trade", "trade", (1150, 170, 1350, 208)),
    Signature("trade", "trade_offer", (1150, 170, 1350, 208)),  # AI の提案中の取引画面
    # Chance / Community Chest のカード。右上の × ボタンで判別する(どのカードでも同じ位置・同じ形)
    Signature("card_dialog", "card_close", (1655, 275, 1750, 355)),
    Signature("improvements", "improvements", (1150, 100, 1340, 150)),  # 建設画面(Manage の先)
    Signature("zoomed_board", "zoomed_board", (290, 380, 382, 460)),  # 拡大表示の盤。建設画面より後
    Signature("game_statistics", "game_statistics", (1140, 240, 1360, 276)),
    Signature("log", "log_open", (1530, 175, 1595, 235)),
    Signature("main_menu", "main_menu", (280, 250, 390, 300)),
    Signature("pause", "pause", (1180, 230, 1330, 268)),
    Signature("board_my_turn_roll", "menu_roll", (290, 270, 385, 372)),
    Signature("board_my_turn_end", "menu_end_turn", (290, 270, 385, 372)),
    # 収監中の Roll 表示。メニューに Post Bail が加わり、Roll の位置がずれる。Roll の操作は同じなので、同じ画面名にする。
    # 収監かどうかは、Log から追う位置の追跡が持つ(画面の名前では分けない)
    Signature("board_my_turn_roll", "menu_post_bail", POST_BAIL_LABEL),
    Signature("board_my_turn_roll", "menu_use_card", USE_CARD_LABEL),
    # 所持金がマイナス(負債)のメニュー: Roll / End Turn の代わりに、Auto Sell と Resign が出る(実機 2026-11-08)。
    # 負債が残る間は、ターンを終えられない。資金調達でプラスに戻すか、Auto Sell / Resign を押す
    # 刑務所で、Roll が無く、Post Bail が一番上のメニュー(保釈金を払わないと進めない。実機 2026-11-08)
    Signature("board_jail_bail_only", "menu_post_bail_top", BAIL_TOP_LABEL),
    Signature("board_debt", "menu_auto_sell", DEBT_LABEL),
    # 刑務所で、現金が保釈金(M50)に足りない: Post Bail / Auto Sell / Trade / Resign が出て、Roll が消える(実機 2026-11-08)
    Signature("board_debt", "menu_auto_sell_jail", JAIL_DEBT_LABEL),
)


@dataclass(frozen=True)
class Screen:
    name: str
    confidence: float  # 当たった画面の相関。UNKNOWN のときは 0.0


@cache
def _template(name: str) -> NDArray[np.uint8]:
    path = TEMPLATE_DIR / f"{name}.png"
    image = load_image(path)
    if image is None:
        raise FileNotFoundError(f"テンプレートが無い: {path}")
    return image


def _score(image: NDArray[np.uint8], sig: Signature) -> float:
    """テンプレートの元の位置の近傍(SEARCH_MARGIN)だけで照合する。"""
    x0, y0, x1, y1 = sig.home
    height, width = image.shape[:2]
    rx0, ry0 = max(0, x0 - SEARCH_MARGIN), max(0, y0 - SEARCH_MARGIN)
    rx1, ry1 = min(width, x1 + SEARCH_MARGIN), min(height, y1 + SEARCH_MARGIN)
    return match_score(image[ry0:ry1, rx0:rx1], _template(sig.template))


def classify(image: NDArray[np.uint8]) -> Screen:
    """画面の種類を返す。どの画面にも当たらないときは UNKNOWN。"""
    if not has_size(image, IMAGE_SIZE):
        return Screen(UNKNOWN, 0.0)
    for sig in SIGNATURES:
        score = _score(image, sig)
        if score >= MATCH_MIN:
            return Screen(sig.name, score)
    return Screen(UNKNOWN, 0.0)


def has_use_card(image: NDArray[np.uint8]) -> bool:
    """メニューに Use Card が出ているか(釈放カードを持つ、収監中の Roll 表示)。"""
    if not has_size(image, IMAGE_SIZE):
        return False
    sig = next(s for s in SIGNATURES if s.template == "menu_use_card")
    return _score(image, sig) >= MATCH_MIN


def has_post_bail(image: NDArray[np.uint8]) -> bool:
    """メニューに Post Bail が出ているか(収監中の Roll 表示)。"""
    if not has_size(image, IMAGE_SIZE):
        return False
    sig = next(s for s in SIGNATURES if s.template == "menu_post_bail")
    return _score(image, sig) >= MATCH_MIN


# 盤の地の色(薄い緑)。端末の色補正(夜間モードなど)が掛かると変わり、色に頼る読み取り(所有の棒、ダイス)が
# 誤る。実機で、青みがかった画面(盤の地が BGR 213,216,159)では、所有の棒が静かに誤読された
BOARD_PROBES = ((600, 1350), (330, 1500), (560, 1000))  # (y, x)。通常の盤の、何も乗らない地の位置
BOARD_COLOR = (206, 231, 206)  # BGR
BOARD_COLOR_TOL = 14


def color_is_normal(image: NDArray[np.uint8]) -> bool:
    """盤の地の色が、通常の範囲か。色補正が掛かっていれば False。メニューが出ている通常の盤だけで使う。"""
    if not has_size(image, IMAGE_SIZE):
        return False
    target = np.array(BOARD_COLOR, dtype=np.int16)
    # サイコロなどが 1 か所の上に載ることがある(実機)。3 か所のうち 2 か所以上が通常色なら通常とみなす。
    # 色補正は盤全体に掛かるので、3 か所とも外れる
    matches = sum(
        int(np.abs(image[y, x].astype(np.int16) - target).max()) <= BOARD_COLOR_TOL
        for y, x in BOARD_PROBES
    )
    return matches >= len(BOARD_PROBES) - 1
