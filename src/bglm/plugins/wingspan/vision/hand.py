"""手札の配置(画面下の扇状の札の、各札の位置)。

札は左から、ボーナス、鳥の順に並ぶ(追跡している手札と同じ順。実機で確認)。左端の札の左端は x ≈ 442、右端(一番新しい)札の
左端は x ≈ 890 で、その間を等間隔に並ぶ(4 枚: 442 / 583 / 737 / 889、5 枚: 440 / 552 / 665 / 777 / 890。実画面で測った)。
右端の札だけ全体が見え、他の札は左端の細い帯だけが見える。札の名前は画面から読めない(重なる)ので、
どの札かは追跡の順で決め、必要なら札をタップで拡大して確かめる(executor)。
"""

from bglm.plugins.wingspan.vision.layout import Rect

HAND_LEFT_FIRST = 442  # 左端の札の左端
HAND_LEFT_LAST = 890  # 右端の札の左端
HAND_Y = 950  # 札の帯をタップする高さ。1030 では拡大しない(実機。RESULT.md §14)
LAST_CARD_W = 340  # 右端の札の見える幅
MAX_STRIP_X = 50  # 細い帯のどこを押すか(左端からの距離の上限)


def card_lefts(count: int) -> list[int]:
    """手札(ボーナスを含む)count 枚の、各札の左端の x。"""
    if count <= 0:
        return []
    if count == 1:
        return [HAND_LEFT_LAST]
    step = (HAND_LEFT_LAST - HAND_LEFT_FIRST) / (count - 1)
    return [round(HAND_LEFT_FIRST + step * i) for i in range(count)]


def card_point(count: int, index: int) -> tuple[int, int]:
    """手札 count 枚のうち、index 番目(0 始まり。左端 = ボーナス)の札を押す位置。

    右端の札は中央、他の札は、次の札に隠れない左端の帯の中。
    """
    lefts = card_lefts(count)
    if not 0 <= index < len(lefts):
        raise IndexError(f"手札 {count} 枚のうち {index} 番目は無い")
    if index == len(lefts) - 1:
        return lefts[index] + LAST_CARD_W // 2, HAND_Y
    strip = lefts[index + 1] - lefts[index]
    return lefts[index] + min(strip // 2, MAX_STRIP_X), HAND_Y


def hand_rect(count: int) -> Rect:
    lefts = card_lefts(count)
    return (lefts[0], 850, lefts[-1] + LAST_CARD_W, 1080) if lefts else (0, 0, 0, 0)
