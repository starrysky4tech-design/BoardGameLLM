"""画面の種類の判別。座標は原寸(2432x1080)で、録画した1ゲームの画像で確かめた。

判別の手がかり(いずれも固定位置の色か、ボタンの文字のテンプレート):
- 全面が一様な濃い青 → 読み込み中
- 左の帯が砂色(R > B) → タイトル・ステージ選択(明るい)、再開確認(暗い)
- 左の帯が青(B > R)で暗い → 対戦中のダイアログ。ボタンの文字で決算(CONTINUE)と終了(NEXT)を分ける
- 左の帯が青で明るい → 対戦。チュートリアルの案内、「READY FOR A NEW ROUND」の帯、
  手札の明暗(自分の手番は明るく、相手の手番は暗く沈む)で分ける
"""

from dataclasses import dataclass

import cv2
import numpy as np
from numpy.typing import NDArray

from bglm.core.models import UiKind
from bglm.plugins.kahuna.vision.templates import TemplateSet

IMAGE_SIZE = (2432, 1080)  # 幅, 高さ

# 画面の名前(ログと評価セットのラベルに使う)
LOADING = "loading"
MENU = "menu"
MENU_DIALOG = "menu_dialog"
TUTORIAL_TIP = "tutorial_tip"
BANNER = "banner"
MY_TURN = "my_turn"
OPPONENT_TURN = "opponent_turn"
ROUND_END = "round_end"
GAME_END = "game_end"
DIALOG = "dialog"
BAD_SIZE = "bad_size"

SIDE_STRIP = (300, 800, 80, 250)  # y0, y1, x0, x1。盤の外の、左の帯
TIP_STRIP = (40, 60, 1000, 1700)
HAND_ROI = (200, 960, 1620, 2010)
DIM_MAX = 80  # 暗い重ね(ダイアログ・再開確認)の、帯の最大チャンネル平均の上限
SAND_BRIGHT_MIN = 150
UNIFORM_STD = 2.0
TIP_RED_MIN = 180  # 案内の羊皮紙の色
BANNER_RED_ROWS = 0.5  # 帯の赤い模様が占める行の割合
HAND_WHITE_MIN = 3.0  # 自分の手番の手札の白い画素の割合(%)。実測は明るい4以上、暗い1未満
BUTTON_ROI = (790, 910, 1000, 1500)
BUTTON_MIN_SCORE = 0.80
BUTTON_CLEARANCE = 0.05  # 2つのボタンの文字の、相関の差


@dataclass(frozen=True)
class Screen:
    name: str
    kind: UiKind
    confidence: float = 1.0


def hand_white_percent(image: NDArray[np.uint8]) -> float:
    y0, y1, x0, x1 = HAND_ROI
    return float((image[y0:y1, x0:x1].min(axis=2) > 200).mean() * 100)


def _banner_present(image: NDArray[np.uint8]) -> bool:
    b, g, r = (image[:, 100:2300, k].astype(np.int16) for k in range(3))
    red_rows = ((r > 150) & (g < 110) & (b < 110)).mean(axis=1)
    return bool(red_rows.max() > BANNER_RED_ROWS)


def _dialog_button(image: NDArray[np.uint8], templates: TemplateSet) -> tuple[str | None, float]:
    y0, y1, x0, x1 = BUTTON_ROI
    gray = np.asarray(cv2.cvtColor(image[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY), dtype=np.uint8)
    scores = {
        name: float(cv2.matchTemplate(gray, templates.dialogs[name], cv2.TM_CCOEFF_NORMED).max())
        for name in ("continue", "next")
    }
    best = max(scores, key=lambda n: scores[n])
    other = min(scores.values())
    if scores[best] >= BUTTON_MIN_SCORE and scores[best] - other >= BUTTON_CLEARANCE:
        return best, scores[best]
    return None, scores[best]


def classify_screen(image: NDArray[np.uint8], templates: TemplateSet) -> Screen:
    if image.shape[:2] != (IMAGE_SIZE[1], IMAGE_SIZE[0]):
        return Screen(BAD_SIZE, UiKind.UNKNOWN)
    if float(image[::20, 100::20].reshape(-1, 3).std(axis=0).max()) < UNIFORM_STD:
        return Screen(LOADING, UiKind.WAITING)

    y0, y1, x0, x1 = SIDE_STRIP
    blue, _, red = image[y0:y1, x0:x1].reshape(-1, 3).mean(axis=0)
    bright = max(blue, red) >= (SAND_BRIGHT_MIN if red > blue else DIM_MAX)
    if red > blue:  # 砂色: タイトル・ステージ選択・再開確認。対戦の開始は人が行う
        return Screen(MENU if bright else MENU_DIALOG, UiKind.UNKNOWN)

    if not bright:  # 対戦の上の暗い重ね
        button, score = _dialog_button(image, templates)
        if button == "continue":
            return Screen(ROUND_END, UiKind.WAITING, score)
        if button == "next":
            return Screen(GAME_END, UiKind.GAME_OVER, score)
        return Screen(DIALOG, UiKind.UNKNOWN)

    ty0, ty1, tx0, tx1 = TIP_STRIP
    if image[ty0:ty1, tx0:tx1].reshape(-1, 3).mean(axis=0)[2] > TIP_RED_MIN:
        return Screen(TUTORIAL_TIP, UiKind.UNKNOWN)
    if _banner_present(image):
        return Screen(BANNER, UiKind.WAITING)
    if hand_white_percent(image) > HAND_WHITE_MIN:
        return Screen(MY_TURN, UiKind.PLAYABLE)
    return Screen(OPPONENT_TURN, UiKind.WAITING)
