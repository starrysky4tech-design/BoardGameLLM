"""土地の管理(抵当に入れる・解除する・家を売る)の実機操作。資金調達(logic/funding.py)の実行に使う。

抵当・解除(実機で確認 2026-11-08): 全体盤の色グループを押す → 案内を消す → 土地を押して詳細(MANAGE PROPERTY)
→ 右下の Mortgage / Unmortgage(同じ位置のボタン)→ 確認ダイアログ → Yes → 拡大盤に戻る。
Mortgage の確認は「mortgage <土地> for ₼30」、Unmortgage は「unmortgage <土地> for ₼33」(₼30 + 利息 ₼3)。

組を全部持つ色グループは、色グループを押すと建設画面が開く。土地は建設画面の土地の本体を押す(家が建つ組の土地は、
家を全て売ってから抵当に入れる)。家の売却は、建設画面の − を押し、Make Changes → Yes(+ の 1 つ左の − の位置)。
"""

import re
from collections.abc import Mapping

from bglm.core.models import ExecutionResult, Point, Tap
from bglm.plugins.monopoly.vision import bars
from bglm.plugins.monopoly.vision import executor as ex
from bglm.plugins.monopoly.vision import navigation as nav
from bglm.plugins.monopoly.vision.builder import change_houses
from bglm.plugins.monopoly.vision.dialog_reader import TextOcr
from bglm.plugins.monopoly.vision.ownership import (
    DETAIL_RETURN_MORTGAGE,
    PROPERTY_GROUP,
    ZOOM_TILE,
)
from bglm.plugins.monopoly.vision.screens import BOARD_SCREENS

DETAIL_ACTION = Point(1482, 976)  # 詳細画面の右下: Mortgage または Unmortgage
STEP_SEC = 2.5


def _to_board(driver: ex.Driver) -> bool:
    """盤の通常の画面へ戻る。通知は OK、取引画面を誤って開いたときは Cancel → Yes で閉じる。それ以外は Return。"""
    return nav.return_to_board(driver, wait_sec=STEP_SEC, close_trade=True)


def _open_detail(driver: ex.Driver, name: str) -> str | None:
    """土地の詳細画面(MANAGE PROPERTY)を開く。開けなければ理由(失敗)を返す。成功なら None。

    開いた後の画面の種類は、呼び出し側が確かめる(詳細画面の判別は、所有者の色の読み取りで代用しない)。
    """
    if name not in PROPERTY_GROUP:
        return f"{name}: 位置が未登録の土地"
    group = PROPERTY_GROUP[name]
    opened = nav.open_group(driver, group)
    if opened.problem:
        return f"{name}: {opened.problem}"
    if opened.screen == "zoomed_board":
        driver.perform(Tap(ZOOM_TILE[name]))
    else:
        view = bars.VIEWS.get(f"improvements_{group}")
        tiles: Mapping[str, int] = dict(view.tiles) if view else {}
        if name not in tiles:
            return f"{name}: 建設画面での位置が未登録"
        driver.perform(
            Tap(Point(round(tiles[name] * bars.DISPLAY_TO_FRAME), nav.IMPROVEMENT_TILE_Y))
        )
    driver.sleep(nav.OPEN_SEC)
    return None


ACTION_LABEL_BOX = (1380, 985, 1620, 1050)  # 詳細画面の右下のボタンの文字(Mortgage / Unmortgage)
CONFIRM_TEXT_BOX = (
    850,
    495,
    1630,
    585,
)  # 確認ダイアログの本文(「Are you sure you want to mortgage ... for ₼30?」)
CONFIRM_NO = Point(1046, 811)  # 確認ダイアログの No(実機 2026-11-08: 表示 857,665)


def confirm_text_matches(text: str, name: str, mortgage: bool) -> bool:
    """確認ダイアログの本文が、期待の操作(抵当に入れる / 解除)と、土地に合うか。読めなければ False。

    Mortgage と Unmortgage は、詳細画面の同じ位置のボタンなので、押した後の本文で確かめる。
    """
    lowered = text.lower().replace(" ", "")
    verb_ok = (
        "unmortgage" in lowered
        if not mortgage
        else ("mortgage" in lowered and "unmortgage" not in lowered)
    )
    letters = re.sub(r"[^a-z]", "", lowered).replace(
        "l", "i"
    )  # OCR は、大文字 I と小文字 l を取り違える
    # 土地名の英字だけを比べる(「B&O Railroad」と「B. & O. Railroad」の表記の違い、「Avenue」の省略を許す)
    key = re.sub(r"[^a-z]", "", name.lower().replace("avenue", "").replace("place", ""))
    first_word = key.replace("l", "i")[:6]
    return verb_ok and first_word in letters


def _set_mortgage(driver: ex.Driver, name: str, mortgage: bool, ocr: TextOcr) -> ExecutionResult:
    """抵当に入れる(mortgage=True)・解除する(False)。盤の通常の画面から始め、盤へ戻す。"""
    if driver.screen() not in BOARD_SCREENS:
        return ex.fail("盤の通常の画面ではない")
    problem = _open_detail(driver, name)
    if problem is not None:
        _to_board(driver)
        return ex.fail(problem)
    label = " ".join(
        i.text for i in ocr.read_box(driver.io.capture().image, ACTION_LABEL_BOX)
    ).lower()
    if mortgage and "unmortgage" in label.replace(" ", ""):
        # 詳細画面のボタンが「Unmortgage」= すでに抵当済み。押さずに閉じる(記録の誤りは、呼び出し側が直す)
        driver.perform(Tap(DETAIL_RETURN_MORTGAGE))
        driver.sleep(STEP_SEC)
        _to_board(driver)
        return ex.fail(f"{name}: すでに抵当済み(ボタンが Unmortgage)")
    driver.perform(Tap(DETAIL_ACTION))
    for _ in range(3):
        driver.sleep(ex.CHANGE_WAIT_SEC)
        if driver.screen() == "confirm_dialog":
            break
    else:
        driver.perform(Tap(DETAIL_RETURN_MORTGAGE))
        driver.sleep(STEP_SEC)
        _to_board(driver)
        return ex.fail(f"{name}: 抵当の確認が出ない(家が建っている、または詳細画面が開いていない)")
    text = " ".join(i.text for i in ocr.read_box(driver.io.capture().image, CONFIRM_TEXT_BOX))
    if not confirm_text_matches(text, name, mortgage):
        driver.perform(Tap(CONFIRM_NO))  # 期待と違う操作(解除と抵当の取り違えなど)は、取り消す
        driver.sleep(STEP_SEC)
        driver.perform(
            Tap(DETAIL_RETURN_MORTGAGE)
        )  # 詳細画面を閉じる(Return の位置は、詳細画面の左下)
        driver.sleep(STEP_SEC)
        _to_board(driver)
        want = "mortgage" if mortgage else "unmortgage"
        return ex.fail(f"{name}: 確認の本文が期待({want})と合わない: {text!r}。取り消した")
    driver.perform(Tap(ex.CONFIRM_YES))
    driver.sleep(STEP_SEC)
    if not _to_board(driver):
        return ex.fail(f"{name}: 盤に戻れない")
    return ExecutionResult(success=True, actions=(Tap(DETAIL_ACTION), Tap(ex.CONFIRM_YES)))


def mortgage(driver: ex.Driver, name: str, ocr: TextOcr) -> ExecutionResult:
    return _set_mortgage(driver, name, mortgage=True, ocr=ocr)


def unmortgage(driver: ex.Driver, name: str, ocr: TextOcr) -> ExecutionResult:
    return _set_mortgage(driver, name, mortgage=False, ocr=ocr)


def sell_houses(driver: ex.Driver, group: str, plan: Mapping[str, int]) -> ExecutionResult:
    """1 つの色グループで、plan(土地 → 売る軒数)の家(ホテル)を売って確定する。

    売る順は、均等に売る規則に合わせ、建てるときと逆(入口に近い土地から)。− を押し、Make Changes → Yes。
    """
    return change_houses(driver, group, plan, sell=True)
