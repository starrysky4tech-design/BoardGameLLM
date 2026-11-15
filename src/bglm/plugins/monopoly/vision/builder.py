"""家の建設(実機)。色グループを押して建設画面を開き、土地の + を押し、Make Changes → Yes で確定する。

位置は、実機(2026-11-07)で確かめた色グループだけ登録する。登録の無い色グループは建てない(推測で押さない)。
建設画面は、自分が組を全部持つときに開く。開いた画面が建設画面でなければ、何も押さずに戻って失敗とする。
家は均等に建てる(ゲームの規則): 1 周ごとに、残りのある土地へ 1 軒ずつ足す。
"""

from collections.abc import Mapping

from bglm.core.models import ExecutionResult, Point, Tap
from bglm.plugins.monopoly.logic.board import POSITION_OF
from bglm.plugins.monopoly.logic.catalogue import CATALOGUE
from bglm.plugins.monopoly.vision import executor as ex
from bglm.plugins.monopoly.vision import navigation as nav
from bglm.plugins.monopoly.vision.screens import BOARD_SCREENS

MAKE_CHANGES = Point(1468, 366)
PLUS_SEC = 1.0
MINUS_OFFSET_X = 98  # 建設画面の、+ の中心から − の中心までの距離(原寸。実機の画面から)

# 建設画面の、土地ごとの + ボタンの位置(原寸)。実機で 1 軒ずつ押して確かめた
PLUS: dict[str, dict[str, Point]] = {
    "pink": {
        "Virginia Avenue": Point(1007, 836),
        "States Avenue": Point(1202, 836),
        "St. Charles Place": Point(1598, 836),
    },
    "red": {  # 実機確認 2026-11-10(Illinois・Kentucky に建設、現金 ₼301 → ₼1)。Indiana は未押下
        "Illinois Avenue": Point(1003, 836),
        "Indiana Avenue": Point(1198, 836),
        "Kentucky Avenue": Point(1596, 836),
    },
    "orange": {
        "New York Avenue": Point(1031, 836),
        "Tennessee Avenue": Point(1226, 836),
        "St. James Place": Point(1623, 836),
    },
    "dark_blue": {
        "Boardwalk": Point(1104, 839),
        "Park Place": Point(1495, 839),
    },
    "green": {
        "Pennsylvania Avenue": Point(1025, 836),
        "North Carolina Avenue": Point(1397, 836),
        "Pacific Avenue": Point(1617, 836),
    },
    "light_blue": {
        "Connecticut Avenue": Point(1035, 830),
        "Vermont Avenue": Point(1226, 830),
        "Oriental Avenue": Point(1623, 830),
    },
}


def far_first(group: str) -> list[str]:
    """色グループの土地を、入口(盤の番号が一番小さい土地)から遠い順に並べる。現金が足りないときも、遠い方が厚くなる。"""
    return sorted(PLUS[group], key=lambda n: -POSITION_OF[n])


def group_of(square: str) -> str | None:
    """土地の名前から、建設画面の色グループ名。登録が無ければ None。"""
    group = CATALOGUE[square].group
    return group if group in PLUS else None


def build_group(driver: ex.Driver, group: str, plan: Mapping[str, int]) -> ExecutionResult:
    """1 つの色グループに、plan(土地 → 軒数)の家を建てて確定する。盤の通常の画面から始め、盤へ戻す。"""
    return change_houses(driver, group, plan, sell=False)


def change_houses(
    driver: ex.Driver, group: str, plan: Mapping[str, int], *, sell: bool
) -> ExecutionResult:
    """建設画面で、plan(土地 → 軒数)の分だけ + (sell なら −)を押し、Make Changes → Yes で確定する。

    建てる順は入口から遠い土地から(現金が足りないときも、遠い方が厚くなる)、売る順はその逆(均等に売る規則)。
    売却は、取引画面を誤って開いたときも閉じて戻る(負債のメニューでは、Return の位置に Trade がある)。
    """
    sign = "−" if sell else "+"
    verb = "売却" if sell else "建設"
    if group not in PLUS:
        return ex.fail(f"{group}: + / − の位置が未登録")
    if set(plan) - set(PLUS[group]) or any(n <= 0 for n in plan.values()):
        return ex.fail(f"{group}: 計画が登録の土地と合わない: {dict(plan)}")
    if driver.screen() not in BOARD_SCREENS:
        return ex.fail("盤の通常の画面ではない")
    opened = nav.open_group(driver, group, want=("improvements",))
    if opened.problem:
        nav.return_to_board(driver, close_trade=sell)
        return ex.fail(f"{group}: 建設画面が開かない({opened.problem})。組を全部持っていない可能性")
    order = far_first(group)
    if sell:
        order.reverse()
    remaining = dict(plan)
    actions: list[Tap] = []
    while any(remaining.values()):
        for name in order:
            if remaining.get(name, 0) <= 0:
                continue
            plus = PLUS[group][name]
            tap = Tap(Point(plus.x - MINUS_OFFSET_X, plus.y) if sell else plus)
            driver.perform(tap)
            driver.sleep(PLUS_SEC)
            actions.append(tap)
            if (
                driver.screen() == "ok_dialog"
            ):  # 現金不足、上限などの通知。押したボタンは効かなかった
                driver.perform(Tap(nav.NOTICE_OK))
                driver.sleep(nav.RETURN_SEC)
                nav.return_to_board(driver, close_trade=sell)
                return ex.fail(
                    f"{group}: {sign} を押したら通知が出た(現金不足など)。{verb}を中止する"
                )
            remaining[name] -= 1
    if driver.screen() != "improvements":
        nav.return_to_board(driver, close_trade=sell)
        return ex.fail(f"{group}: {sign} を押した後に、建設画面でなくなった")
    result = ex.confirm(driver, MAKE_CHANGES, {"improvements"}, {"improvements"})
    returned = nav.return_to_board(driver, close_trade=sell)
    if not returned:
        return ex.fail(f"{group}: 盤に戻れない")
    if not result.success:
        return ex.fail(f"{group}: 確定できない: {result.reason}")
    return ExecutionResult(success=True, actions=(*actions, *result.actions))
