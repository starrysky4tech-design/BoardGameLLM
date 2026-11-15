"""全体ボードに、誰の盤が映っているか(自分 / 相手)と、相手の手番の最中かを、画面上部の肖像と印から決める。

肖像は 2 つ並び、先手によって左右が入れ替わる。青い冠羽の鳥が自分、橙の鳥が相手(2 局目の実機で確認)。
- **表示中の盤の持ち主の肖像の下に、目の印が出る**(自分の盤では出ない)。目の印はテンプレートで探す
  (パネルの紙の色では、大きい方の肖像の下端と区別できなかった)。目の印が無ければ自分の盤
- **相手の手番の最中は、橙の肖像が大きくなり、その下に砂時計が出る**(確定の約 1.2 秒後に確認。AI の手番は数秒で終わる)
判別できなければ UNKNOWN / None(推測しない)。
"""

from enum import StrEnum
from functools import cache
from pathlib import Path

import cv2
import numpy as np

from bglm.plugins.wingspan.vision.mat import Image

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "data" / "templates" / "viewing"
TEMPLATE = TEMPLATE_DIR / "eye.png"
HOURGLASS = TEMPLATE_DIR / "hourglass.png"
EYE_SEARCH = (1080, 70, 1340, 112)  # 目の印を探す範囲(2 つの肖像の下)
HOURGLASS_SEARCH = (1080, 85, 1340, 145)  # 砂時計を探す範囲
MIN_SCORE = 0.70
FACE_Y = (15, 68)  # 肖像の y の範囲
FACE_HALF_W = 40


class Viewing(StrEnum):
    ME = "me"
    OPPONENT = "opponent"
    UNKNOWN = "unknown"


@cache
def _load(path: Path) -> np.ndarray | None:
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    return None if image is None else np.asarray(image)


def _find(image: Image, path: Path, search: tuple[int, int, int, int]) -> tuple[int, float] | None:
    """テンプレートを範囲内で探し、中心の x と照合スコアを返す。見つからなければ None。"""
    template = _load(path)
    if template is None:
        return None
    x0, y0, x1, y1 = search
    gray = cv2.cvtColor(image[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    result = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, loc = cv2.minMaxLoc(result)
    if score < MIN_SCORE:
        return None
    return x0 + loc[0] + template.shape[1] // 2, float(score)


def find_eye(image: Image) -> tuple[int, float] | None:
    return _find(image, TEMPLATE, EYE_SEARCH)


def find_hourglass(image: Image) -> tuple[int, float] | None:
    return _find(image, HOURGLASS, HOURGLASS_SEARCH)


def _portrait_owner(image: Image, x: int) -> Viewing:
    """印のすぐ上の肖像の色から持ち主を決める。橙 = 相手、青 = 自分。"""
    patch = image[FACE_Y[0] : FACE_Y[1], x - FACE_HALF_W : x + FACE_HALF_W]
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    h, s = hsv[..., 0].astype(np.int16), hsv[..., 1]
    orange = float(np.mean(((h <= 18) | (h >= 170)) & (s >= 90)))
    blue = float(np.mean((h >= 90) & (h <= 110) & (s >= 70)))
    if orange > 0.08 and orange > blue * 1.5:
        return Viewing.OPPONENT
    if blue > 0.08 and blue > orange * 1.5:
        return Viewing.ME
    return Viewing.UNKNOWN


def viewing(image: Image) -> Viewing:
    """表示中の盤の持ち主。目の印が無ければ自分の盤。テンプレートが無いときは UNKNOWN。"""
    if _load(TEMPLATE) is None:
        return Viewing.UNKNOWN
    eye = find_eye(image)
    return Viewing.ME if eye is None else _portrait_owner(image, eye[0])


def opponent_is_playing(image: Image) -> bool | None:
    """相手の手番の最中か(橙の肖像の下に砂時計)。テンプレートが無いときは None。

    砂時計が青い肖像の下に出る場面は未確認なので、その場合も None(自分の手番とは決めない)。
    """
    if _load(HOURGLASS) is None:
        return None
    found = find_hourglass(image)
    if found is None:
        return False
    return True if _portrait_owner(image, found[0]) is Viewing.OPPONENT else None
