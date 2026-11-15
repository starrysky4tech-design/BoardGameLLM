"""画面種別の判別。盤を読んでよい画面か、どんな表示かを、色の特徴だけで決める(OCR もテンプレートも使わない)。

2026-11-13 に、実機の保存画面 324 枚で特徴量を測って閾値を決めた(RESULT.md §2、§9〜§11)。

- 全体ボード(MAT): 盤の上端の帯(革色)が見える。札の重なり(引く画面の大きい札など)は、色では見分けない
- 生息地の表示: 左端に 4 つの色の菱形(紫・緑・橙・青)が縦に並ぶ
- 中央の大きなパネル(手番の開始、ラウンドの採点、終局、確認): 中央が紙の色で覆われる
- 右下の案内パネル(決定の案内): 右下が紙の色。`prompt` が真

**札の重なりを色で見分けない理由**: 札が各行に 3 羽あるだけで、中央の紙色は 0.36 になる(合成画像で確認)。引く画面の大きい札(0.49〜0.51)と区別できない。
そのため、盤を読んでよいのは「MAT で、案内パネルが無い(決定を待っていない)」ときだけとし、読んだ結果は追跡している状態と照合する
(食い違えば止まる)。ダイアログは 0.73〜0.92 で、札を全枠に貼った合成の盤(0.63)とは分かれる。判別できない画面は UNKNOWN とし、入力を送らない。
"""

from dataclasses import dataclass
from enum import StrEnum

import cv2
import numpy as np

from bglm.plugins.wingspan.vision.mat import Image, paper_fraction

Rect = tuple[int, int, int, int]

BOARD_STRIP: Rect = (500, 100, 1900, 122)  # 盤の上端。卵のコストの印より上で、革色だけが見える
CENTER: Rect = (760, 280, 1680, 780)  # 中央のパネルが覆う範囲
PROMPT_PANEL: Rect = (2010, 800, 2200, 960)  # 案内パネルの右側(カードトレイより右)
CONFIRM_PANEL: Rect = (
    960,
    330,
    1460,
    740,
)  # 確認ダイアログ(スキップなど)の紙のパネルの中。背景は暗くなる

# 生息地の表示の 4 つの菱形: (中心 x, 中心 y, OpenCV の色相)。紫、緑、橙、青
DIAMONDS: tuple[tuple[int, int, int], ...] = (
    (141, 152, 140),
    (141, 302, 62),
    (141, 459, 18),
    (141, 602, 105),
)

# 盤の上端の帯で革色がこれ以上なら、全体ボードの表示。札を選んだ後の引く画面は、持ち上がった大きい札が上端を覆い、
# 1 枚で 0.43〜0.47、2 枚で 0.30、3 枚で 0.20 まで下がる(実測)。盤以外の画面は 0.15 未満
LEATHER_MIN = 0.18
DIALOG_MIN = 0.70  # 中央がこれ以上紙の色なら、中央のパネルが出ている
HABITAT_CENTER_MAX = 0.45  # 生息地の表示は、中央がこれ未満(初期選択の画面は 0.58 以上)
PROMPT_MIN = 0.50  # 右下の案内パネルの紙の色
CONFIRM_MIN = 0.75  # 確認ダイアログのパネルの内側の紙の色(候補。文言は OCR で確かめる)
DIAMONDS_MIN = 3  # 4 つのうち、これ以上の菱形が見えれば生息地の表示


class ScreenKind(StrEnum):
    MAT = "mat"  # 全体ボード(大きい札やパネルが重なることがある)
    HABITAT = "habitat"  # 生息地の表示
    DIALOG = "dialog"  # 中央の大きなパネル
    CONFIRM = "confirm"  # 確認ダイアログの候補(スキップなど。文言は OCR で確かめる)
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ScreenInfo:
    kind: ScreenKind
    prompt: bool  # 右下に案内パネル(決定の案内)がある


def _leather_fraction(image: Image, rect: Rect) -> float:
    x0, y0, x1, y1 = rect
    hsv = cv2.cvtColor(image[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    return float(np.mean((hue >= 5) & (hue <= 22) & (sat >= 90) & (val >= 60) & (val <= 200)))


DIAMOND_SHIFT = (
    60  # 画面の描画が左右にずれても見つける範囲(実機: 新しい対局で 141 → 97 と、左へ約 44px ずれた)
)


def _diamond_visible(image: Image, cx: int, cy: int, hue: int) -> bool:
    x0 = max(0, cx - 18 - DIAMOND_SHIFT)
    hsv = cv2.cvtColor(image[cy - 18 : cy + 18, x0 : cx + 18 + DIAMOND_SHIFT], cv2.COLOR_BGR2HSV)
    h = hsv[..., 0].astype(np.int16)
    mask = (np.abs(h - hue) <= 10) & (hsv[..., 1] >= 110) & (hsv[..., 2] >= 90)
    # 幅方向に動かした窓の中で、36 px 幅あたりの最大の割合(ずれた菱形を、1 つの窓に収める)
    columns = mask.mean(axis=0)
    width = 36
    if columns.size < width:
        return False
    window = np.convolve(columns, np.ones(width) / width, mode="valid")
    return float(window.max()) >= 0.3


def classify(image: Image) -> ScreenInfo:
    """画面種別と、案内パネルの有無。画像は原寸(2432x1080)。"""
    if image.shape[:2] != (1080, 2432):
        return ScreenInfo(ScreenKind.UNKNOWN, False)
    center = paper_fraction(image, CENTER)
    prompt = paper_fraction(image, PROMPT_PANEL) >= PROMPT_MIN
    if center >= DIALOG_MIN:
        return ScreenInfo(ScreenKind.DIALOG, False)
    if paper_fraction(image, CONFIRM_PANEL) >= CONFIRM_MIN:
        return ScreenInfo(ScreenKind.CONFIRM, False)
    if _leather_fraction(image, BOARD_STRIP) >= LEATHER_MIN:
        return ScreenInfo(ScreenKind.MAT, prompt)
    visible = sum(_diamond_visible(image, *d) for d in DIAMONDS)
    if visible >= DIAMONDS_MIN and center < HABITAT_CENTER_MAX:
        return ScreenInfo(ScreenKind.HABITAT, prompt)
    return ScreenInfo(ScreenKind.UNKNOWN, False)


TOAST_BANNER: Rect = (
    760,
    60,
    1740,
    190,
)  # Android の通知(「実績を達成しました」など)の帯。画面の上端中央に重なる
TOAST_DARK_MIN = (
    0.80  # 帯の中で暗い画素(R、G、B のどれも 70 未満)の割合。盤・メニューは 0.0〜0.13、通知は 0.95
)


def is_toast(image: Image) -> bool:
    """OS の通知(実績の解除など)が上端に重なっているか。数秒で消えるので、待てばよい(盤の判別は崩れる)。

    暗い背景のダイアログ(確認)も帯が暗くなるが、それは `classify` が先に CONFIRM と決める。呼ぶのは UNKNOWN のときだけ。
    """
    x0, y0, x1, y1 = TOAST_BANNER
    crop = image[y0:y1, x0:x1]
    return crop.size > 0 and float(np.mean(crop.max(axis=2) < 70)) >= TOAST_DARK_MIN
