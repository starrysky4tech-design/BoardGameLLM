"""Monopoly の手を、実機の入力に変える(MoveExecutor の一部)。座標は COORDINATES.md(実機で確認した値)。

各操作は、次の順で行う:
1. 前提の画面を確かめる(違えば入力を送らず失敗)
2. 入力を送る
3. 想定の画面に変わったかを確かめる(変わらなければ、上限まで再試行。それでも変わらなければ失敗)

入力の前に、ロール表示が出てから 3 秒待つ(COORDINATES.md: 直後に押すと反映されないことがある)。
失敗は例外にせず ExecutionResult(success=False, reason=...) で返す。呼び出し側(実行ループ)が停止する。
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from bglm.core.models import ExecutionResult, HoldDrag, InputAction, Point, Tap
from bglm.core.protocols import GameIo
from bglm.plugins.monopoly.vision.screens import classify, has_post_bail, has_use_card
from bglm.toolkit.waiting import poll

ROLL_FROM = Point(1257, 763)  # Roll ボタン
ROLL_TO = Point(1257, 300)  # 上へ移動して離す
ROLL_HOLD_MS = 600
ROLL_STEPS = 6
ROLL_STEP_MS = 40
ROLL_SETTLE_SEC = 3.0  # Roll 表示の直後は、押しても反映されないことがある(12 回中 12 回成功の条件)
ROLL_WAIT_SEC = 9.0  # ロールの結果が出るまで。実機の計測で約 9 秒

END_TURN = Point(330, 320)
CARD_CLOSE = Point(
    1702, 315
)  # Chance / Community Chest のカードの × ボタン(実機 2026-11-04・05 で確認)
TRADE_CANCEL = Point(1050, 875)
TRADE_CANCEL_YES = Point(1462, 800)
USE_CARD = Point(
    333, 317
)  # 釈放カードを持つメニューの Use Card(実機 2026-11-08 の画面から計算。未確認)
POST_BAIL_TOP = Point(
    333, 323
)  # Roll が無いメニューで、いちばん上の Post Bail(実機 2026-11-08 の画面から計算)
POST_BAIL_WITH_CARD = Point(333, 421)  # 同じメニューの Post Bail(未確認)
POST_BAIL = Point(
    332, 372
)  # 収監中(Roll 表示)の Post Bail。メニューに「Post Bail」の文字があるときだけ押す
JAIL_YES = Point(1462, 800)

# 確定の操作(2026-11-05 の実機で確認)。どの確認ダイアログも、Yes は同じ位置
CONFIRM_YES = Point(1466, 781)
BUY = Point(1515, 854)
PASS = Point(995, 854)
BID = Point(1662, 268)  # オークションの Bid ボタン
FORFEIT = Point(
    1662, 634
)  # オークションの Forfeit(アイコンの位置。2026-11-05 に計算。実機での確認は未了)
KEYPAD_ACCEPT = Point(1348, 793)
KEYPAD_CANCEL = Point(1165, 790)
# キーパッドの数字(原寸)。押すたびに表示を確かめる(続けて押すと、桁が増えて誤入札になる)
KEYPAD_DIGITS: dict[str, Point] = {
    "1": Point(1165, 445),
    "2": Point(1257, 445),
    "3": Point(1345, 445),
    "4": Point(1165, 540),
    "5": Point(1257, 540),
    "6": Point(1345, 540),
    "7": Point(1165, 620),
    "8": Point(1257, 620),
    "9": Point(1345, 620),
    "0": Point(1257, 701),
}
TRADE_ACCEPT = Point(1455, 872)
TRADE_DECLINE = Point(1053, 878)

CHANGE_WAIT_SEC = 2.0  # 画面の変化を待つ間隔(Android の描画の遅れ)
UNCHANGED_LIMIT = 2  # 操作しても変わらない回数の上限(config/monopoly.toml の既定と一致)
JAIL_CONFIRM_TRIES = (
    4  # 刑務所の確認ダイアログを待つ回数(出るまでに 2 秒以上かかることがある。実機)
)


@dataclass
class Driver:
    """実機の入力と時間。テストでは偽物に差し替える。"""

    io: GameIo
    sleep: Callable[[float], None]
    log: list[str] = field(default_factory=list)

    def screen(self) -> str:
        return classify(self.io.capture().image).name

    def perform(self, action: InputAction) -> None:
        self.io.perform(action)


def fail(reason: str) -> ExecutionResult:
    return ExecutionResult(success=False, reason=reason)


def _tap_until(
    driver: Driver,
    action: InputAction,
    before: set[str],
    after: set[str],
    wait_sec: float = CHANGE_WAIT_SEC,
) -> ExecutionResult:
    """画面が before のときに action を送り、after に変わるまで確かめる。変わらなければ再試行する。"""
    for attempt in range(UNCHANGED_LIMIT):
        if driver.screen() not in before:
            return fail(f"前提の画面と違う(想定 {sorted(before)})")
        driver.perform(action)
        driver.sleep(wait_sec)
        now = driver.screen()
        if now in after:
            return ExecutionResult(success=True, actions=(action,))
        driver.log.append(f"変わらない({attempt + 1} 回目): {now}")
    return fail(f"操作しても画面が変わらない(想定 {sorted(after)})")


def roll(driver: Driver) -> ExecutionResult:
    """Roll: 保持して上へ移動する。Roll 表示 → End Turn 表示。"""
    if driver.screen() != "board_my_turn_roll":
        return fail("Roll の画面ではない")
    hold = HoldDrag(ROLL_FROM, ROLL_TO, ROLL_HOLD_MS, ROLL_STEPS, ROLL_STEP_MS)
    for attempt in range(UNCHANGED_LIMIT):
        driver.sleep(ROLL_SETTLE_SEC)
        driver.perform(hold)
        driver.sleep(ROLL_WAIT_SEC)
        now = driver.screen()
        if now == "board_my_turn_end":
            return ExecutionResult(success=True, actions=(hold,))
        if now == "unknown":
            # ロールの結果に、カード表示などが割り込むことがある。反映済みとして返し、閉じるのは呼び出し側
            return ExecutionResult(success=True, actions=(hold,), reason="結果の表示が割り込んだ")
        driver.log.append(f"ロールが反映されない({attempt + 1} 回目): {now}")
    return fail("ロールが反映されない(上限まで再試行)")


def end_turn(driver: Driver) -> ExecutionResult:
    """End Turn: 自分の手番を終え、AI の手番へ。"""
    return _tap_until(
        driver,
        Tap(END_TURN),
        before={"board_my_turn_end"},
        after={"board_ai_turn", "unknown", "board_my_turn_roll"},
        wait_sec=CHANGE_WAIT_SEC,
    )


def cancel_trade(driver: Driver) -> ExecutionResult:
    """取引画面を Cancel し、確認の Yes で取りやめる(取引は成立しない)。"""
    first = _tap_until(
        driver,
        Tap(TRADE_CANCEL),
        before={"trade"},
        after={"confirm_dialog"},
    )
    if not first.success:
        return first
    driver.perform(Tap(TRADE_CANCEL_YES))
    driver.sleep(CHANGE_WAIT_SEC)
    if driver.screen() in {"trade", "confirm_dialog"}:
        return fail("取引のキャンセルが終わらない")
    return ExecutionResult(success=True, actions=(Tap(TRADE_CANCEL), Tap(TRADE_CANCEL_YES)))


def _jail_confirm(driver: Driver, button: Point, label: str) -> ExecutionResult:
    """刑務所のメニューのボタンを押し、確認(jail_dialog)が出るのを待って、Yes を押す。

    確認ダイアログは、出るまでに 2 秒以上かかることがある(実機)。出ないまま Yes の位置は押さない。
    """
    driver.perform(Tap(button))
    _, shown = poll(
        driver.screen,
        lambda name: name == "jail_dialog",
        tries=JAIL_CONFIRM_TRIES,
        wait_sec=CHANGE_WAIT_SEC,
        sleep=driver.sleep,
        wait_first=True,
    )
    if not shown:
        return fail(f"{label} の確認が出ない")
    driver.perform(Tap(JAIL_YES))
    driver.sleep(CHANGE_WAIT_SEC)
    return ExecutionResult(success=True, actions=(Tap(button), Tap(JAIL_YES)))


def pay_bail(driver: Driver) -> ExecutionResult:
    """収監中に ₼50 を払って出る。収監の確認(jail_dialog)で Yes。戦績に影響する操作。"""
    image = driver.io.capture().image
    if has_use_card(image):
        bail_at = POST_BAIL_WITH_CARD
    elif has_post_bail(image):
        bail_at = POST_BAIL
    else:
        return fail("収監中の画面ではない(Post Bail の表示を確かめられない)")
    return _jail_confirm(driver, bail_at, "Post Bail")


def pay_bail_top(driver: Driver) -> ExecutionResult:
    """Roll が無いメニュー(刑務所、保釈金を払うしかない)の Post Bail → 確認(JAIL ダイアログ)→ Yes。"""
    if driver.screen() != "board_jail_bail_only":
        return fail("Post Bail だけのメニューではない")
    return _jail_confirm(driver, POST_BAIL_TOP, "Post Bail")


def use_jail_card(driver: Driver) -> ExecutionResult:
    """釈放カードを使う: Use Card → 確認(JAIL ダイアログ)→ Yes。メニューに Use Card があるときだけ。"""
    if not has_use_card(driver.io.capture().image):
        return fail("Use Card が出ていない(釈放カードを持っていない、または収監中でない)")
    return _jail_confirm(driver, USE_CARD, "Use Card")


def close_card(driver: Driver) -> ExecutionResult:
    """Chance / Community Chest のカードを閉じる。カードの効果は、閉じる前に呼び出し側が読む。"""
    if driver.screen() != "card_dialog":
        return fail("カードの画面ではない")
    action = Tap(CARD_CLOSE)
    for attempt in range(UNCHANGED_LIMIT):
        driver.perform(action)
        driver.sleep(CHANGE_WAIT_SEC)
        if driver.screen() != "card_dialog":
            return ExecutionResult(success=True, actions=(action,))
        driver.log.append(f"カードが閉じない({attempt + 1} 回目)")
    return fail("カードが閉じない(上限まで再試行)")


def confirm(driver: Driver, first: Point, before: set[str], settle: set[str]) -> ExecutionResult:
    """操作 → 確認ダイアログ(confirm_dialog)→ Yes。

    first を押して、画面が confirm_dialog になったら Yes を押す。ならなければ、押し直す(上限まで)。
    Yes の後、settle のどれかになれば成功。確認ダイアログが出ないまま Yes の位置を押すことはしない。
    """
    action = Tap(first)
    for attempt in range(UNCHANGED_LIMIT):
        if driver.screen() not in before:
            return fail(f"前提の画面と違う(想定 {sorted(before)})")
        driver.perform(action)
        driver.sleep(CHANGE_WAIT_SEC)
        if driver.screen() == "confirm_dialog":
            break
        driver.log.append(f"確認が出ない({attempt + 1} 回目)")
    else:
        return fail("操作しても確認ダイアログが出ない(上限まで再試行)")
    driver.perform(Tap(CONFIRM_YES))
    driver.sleep(CHANGE_WAIT_SEC)
    if driver.screen() in settle:
        return ExecutionResult(success=True, actions=(action, Tap(CONFIRM_YES)))
    return fail("Yes の後に、想定の画面にならない")


def buy(driver: Driver) -> ExecutionResult:
    """購入: Buy → Yes。購入の画面(buy_dialog)から。戦績に影響する。"""
    return confirm(
        driver,
        BUY,
        {"buy_dialog"},
        {"board_my_turn_end", "board_my_turn_roll", "card_dialog", "unknown"},
    )


def pass_on_purchase(driver: Driver) -> ExecutionResult:
    """見送り: Pass → Yes。オークションが始まる(Dog が入札する)。"""
    return confirm(driver, PASS, {"buy_dialog"}, {"auction", "unknown"})


def forfeit(driver: Driver) -> ExecutionResult:
    """オークションを降りる: Forfeit → Yes。Forfeit の位置は、実機での確認が未了(要注意)。"""
    return confirm(
        driver,
        FORFEIT,
        {"auction"},
        {"board_my_turn_end", "board_my_turn_roll", "card_dialog", "unknown"},
    )


def bid(driver: Driver, amount: int) -> ExecutionResult:
    """入札: Bid → キーパッドに amount を 1 桁ずつ入れ(各桁の後に表示を確かめる)→ ACCEPT。

    表示の確認は、画面の判別にキーパッドの数字を読む手段が無いので、ここでは行えない。呼び出し側(または
    OCR)が確かめること。確かめられない間は、桁数が少ない額(3 桁まで)に限る。
    """
    if driver.screen() != "auction":
        return fail("オークションの画面ではない")
    if not 1 <= amount <= 999:
        return fail(f"入札額が範囲外(1〜999): {amount}")
    first = _tap_until(driver, Tap(BID), {"auction"}, {"bid_keypad"})
    if not first.success:
        return first
    actions: list[InputAction] = [Tap(BID)]
    for digit in str(amount):
        tap = Tap(KEYPAD_DIGITS[digit])
        driver.perform(tap)
        driver.sleep(1.0)
        actions.append(tap)
        if driver.screen() != "bid_keypad":
            return fail("数字を押した後に、キーパッドが閉じた(位置のずれの疑い)")
    driver.perform(Tap(KEYPAD_ACCEPT))
    driver.sleep(CHANGE_WAIT_SEC)
    actions.append(Tap(KEYPAD_ACCEPT))
    if driver.screen() == "bid_keypad":
        return fail("ACCEPT の後も、キーパッドが閉じない")
    return ExecutionResult(success=True, actions=tuple(actions))


def respond_to_trade(driver: Driver, accept: bool) -> ExecutionResult:
    """AI の取引の提案に答える。

    - 断る(accept=False): Decline Trade → Yes。実機で確認済み(2026-11-05)
    - 受ける(accept=True): Accept Trade を押す。確認ダイアログが出たら Yes。出ずに盤へ戻っても成功。
      実機での流れは未確認(受ける提案が来ていない)。各段階で画面を確かめ、想定外なら止める
    """
    settle = {"board_my_turn_end", "board_my_turn_roll", "card_dialog", "unknown"}
    if not accept:
        return confirm(driver, TRADE_DECLINE, {"trade"}, settle)
    if driver.screen() != "trade":
        return fail("取引の画面ではない")
    driver.perform(Tap(TRADE_ACCEPT))
    driver.sleep(CHANGE_WAIT_SEC)
    now = driver.screen()
    if now == "confirm_dialog":
        driver.perform(Tap(CONFIRM_YES))
        driver.sleep(CHANGE_WAIT_SEC)
        now = driver.screen()
    if now in settle:
        return ExecutionResult(success=True, actions=(Tap(TRADE_ACCEPT),))
    return fail(f"Accept Trade の後の画面が想定外: {now}")
