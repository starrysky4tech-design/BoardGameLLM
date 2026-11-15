"""盤・拡大盤・建設画面の間の移動(共通部品)。

建設(builder)、抵当・家の売却(property_manager)、所有と家の読み取り(holdings)、実行ループ(runtime)が、
それぞれ持っていた「盤の通常の画面へ戻る」「色グループを開いて案内を消す」を 1 つにまとめた。

- 戻る前後は、画面を取得して確かめる(盤の上の別のボタンを押さない)
- 想定外の画面には、案内を消すタップを送らない
- 案内を消すタップが通知ダイアログを出すことがある(実機)。OK で閉じて、取り直す
"""

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from bglm.core.models import Point, Tap
from bglm.plugins.monopoly.vision import executor as ex
from bglm.plugins.monopoly.vision.executor import Driver
from bglm.plugins.monopoly.vision.ownership import HELP_DISMISS, ZOOM_ENTRY, ZOOM_RETURN
from bglm.plugins.monopoly.vision.screens import BOARD_SCREENS, classify, color_is_normal
from bglm.toolkit.waiting import poll

NOTICE_OK = Point(1254, 811)  # 通知ダイアログ(ok_dialog)の OK(実機で確認)
# 負債のメニューでは、Return の位置に Trade がある(実機)。誤って開いた取引画面の Cancel
TRADE_CANCEL = Point(1054, 903)
IMPROVEMENT_TILE_Y = 634  # 建設画面で、土地の本体を押す y(原寸)

OPEN_SEC = 3.0  # 色グループを押した後、画面の描画を待つ
HELP_SEC = 2.0  # 案内を消した後
RETURN_SEC = 2.5  # 戻る操作の後
WAIT_SEC = (
    0.5  # 期待の画面になるまで取り直す前の待ち(取得自体に約 2 秒かかるので、取得が待ちになる)
)
WAIT_CAPTURES = 3  # 期待の画面になるまで、取り直す回数の上限
RETURN_TRIES = 5

ZOOM_SCREENS = ("zoomed_board", "improvements")  # 色グループを押して開く画面


def capture(driver: Driver) -> tuple[NDArray[np.uint8], str]:
    """画面を 1 回取得して、画像と画面名を返す(判別と読み取りに、同じ画像を使う)。"""
    image: NDArray[np.uint8] = driver.io.capture().image
    return image, classify(image).name


def wait_for(
    driver: Driver, wanted: tuple[str, ...], wait_sec: float = WAIT_SEC
) -> tuple[NDArray[np.uint8], str]:
    """期待の画面のどれかになるまで、画面を取り直す(最後に取った画面を返す)。"""
    last, _ = poll(
        lambda: capture(driver),
        lambda shot: shot[1] in wanted,
        tries=WAIT_CAPTURES,
        wait_sec=wait_sec,
        sleep=driver.sleep,
    )
    return last


def return_to_board(
    driver: Driver,
    *,
    wait_sec: float = RETURN_SEC,
    check_color: bool = False,
    close_trade: bool = False,
) -> bool:
    """拡大盤・建設画面・通知から、盤の通常の画面へ戻る。戻るたびに画面を確かめる。

    通知ダイアログは OK で閉じ、それ以外は Return を押す。
    check_color: 戻った盤の色が通常でなければ False(端末の色補正があると、色に頼る読み取りが誤る)。
    close_trade: 取引画面を誤って開いたとき、Cancel → Yes で閉じる(土地の管理から呼ぶときだけ。
      AI の提案を断る操作と紛れないよう、他の経路では閉じない)。
    """
    for _ in range(RETURN_TRIES):
        image, name = capture(driver)
        if name in BOARD_SCREENS:
            return color_is_normal(image) if check_color else True
        if name == "ok_dialog":
            driver.perform(Tap(NOTICE_OK))
        elif name == "trade" and close_trade:
            driver.perform(Tap(TRADE_CANCEL))
            driver.sleep(wait_sec)
            driver.perform(Tap(ex.CONFIRM_YES))
        else:
            driver.perform(Tap(ZOOM_RETURN))
        driver.sleep(wait_sec)
    image, name = capture(driver)
    return name in BOARD_SCREENS and (color_is_normal(image) if check_color else True)


@dataclass(frozen=True)
class Opened:
    """色グループを開いた結果。problem が空なら、screen の画面が開いていて、image は案内を消した後の画像。"""

    screen: str
    image: NDArray[np.uint8]
    problem: str = ""


def open_group(
    driver: Driver,
    group: str,
    *,
    want: tuple[str, ...] = ZOOM_SCREENS,
    open_sec: float = OPEN_SEC,
    help_sec: float = HELP_SEC,
) -> Opened:
    """盤から色グループを押し、開いた画面の案内を消す。

    自分が組を全部持つと建設画面、そうでなければ拡大盤が開く。開いた画面が want に無ければ、案内を消すタップを
    送らず、problem を返す(呼び出し側が return_to_board で戻す)。案内を消した後に画面が変わった場合も problem。
    """
    driver.perform(Tap(ZOOM_ENTRY[group]))
    driver.sleep(open_sec)
    image, opened = wait_for(driver, want)
    if opened not in want:
        return Opened(opened, image, f"開いた画面が想定と違う: {opened}")
    driver.perform(Tap(HELP_DISMISS))
    driver.sleep(help_sec)
    image, now = wait_for(driver, (opened,))
    if now == "ok_dialog":  # 案内を消すタップが通知を出した。閉じて、取り直す
        driver.log.append(f"{group}: 案内を消すタップが通知ダイアログを出した(OK で閉じた)")
        driver.perform(Tap(NOTICE_OK))
        driver.sleep(help_sec)
        image, now = wait_for(driver, (opened,))
    if now != opened:
        return Opened(now, image, f"案内を消した後に画面が変わった({opened} → {now})")
    return Opened(opened, image)
