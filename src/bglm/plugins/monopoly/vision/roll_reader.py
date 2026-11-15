"""Roll の後の出目を、人手なしで取る(視点の確認、静止の確認、今回の出目の切り分け)。

通常の視点(メニューが出ている盤: board_my_turn_roll / board_my_turn_end)でだけ読む。
AI の手番や、Roll 直後のカメラの移動中は、盤が傾いてメニューが隠れる。その画面では、前の手番の目が
そのまま読めてしまうことがある(実機で確認: 傾いた画面から前の手番の 4・5 が読めた)ので、読まない。

誰の出目か: 自分の Roll の前に、盤に残っている出目(直前の AI の出目)を `arm` で記録する。
Roll の後、点の位置が動いていれば、今回の出目。動いていなければ、Roll が反映されていない(出目なし)。
ダブルの振り直しも、直前の出目と比べるので、同じ仕組みで切り分けられる。

静止: 連続 2 回の取得で、点の位置が同じ(各軸 SAME_TOL px 以内)なら、ダイスは止まっている。
カードやダイアログが盤を覆っているときは、メニューが隠れるので、待つ。閉じるのは呼び出し側の役目で、
閉じた後に `collect` をもう一度呼べる(`arm` の記録は残る)。
"""

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from bglm.core.models import HoldDrag
from bglm.plugins.monopoly.vision import executor as ex
from bglm.plugins.monopoly.vision.dice import Point, read_with_pips
from bglm.plugins.monopoly.vision.executor import Driver
from bglm.plugins.monopoly.vision.screens import Screen, color_is_normal
from bglm.plugins.monopoly.vision.screens import classify as classify_screen

MENU_SCREENS = frozenset({"board_my_turn_roll", "board_my_turn_end"})
SAME_TOL = 3  # 点の位置が同じとみなす差(各軸、px)。同じ静止画のノイズは 1 px 以内
POLL_SEC = 1.0  # 取得の間隔
SETTLE_POLLS = 12  # 静止を待つ取得回数の上限
COLLECT_ATTEMPTS = 3  # 出目が前と同じとき(Roll の反映が遅れているとき)に、待ち直す回数


@dataclass(frozen=True)
class DiceSnapshot:
    values: tuple[int, ...]
    pips: tuple[Point, ...]


@dataclass(frozen=True)
class RollRead:
    values: tuple[int, ...] | None  # 今回の出目(ダイスごと)。読めなければ None
    reason: str = ""  # values が None のときの理由

    @property
    def total(self) -> int | None:
        return sum(self.values) if self.values else None

    @property
    def is_doubles(self) -> bool:
        return (
            self.values is not None and len(self.values) == 2 and self.values[0] == self.values[1]
        )


def snapshot(image: NDArray[np.uint8]) -> DiceSnapshot | None:
    reading, pips = read_with_pips(image)
    if reading.values is None:
        return None
    return DiceSnapshot(reading.values, pips)


def same_dice(a: DiceSnapshot, b: DiceSnapshot, tol: int = SAME_TOL) -> bool:
    """2 つの読み取りが、同じ静止画のダイスか。点の数が同じで、すべての点が tol 以内にある。"""
    if len(a.pips) != len(b.pips):
        return False
    return all(
        abs(p[0] - q[0]) <= tol and abs(p[1] - q[1]) <= tol
        for p, q in zip(a.pips, b.pips, strict=True)
    )


class RollWatcher:
    """Roll の前後の出目を見て、今回の出目だけを返す。"""

    def __init__(
        self,
        driver: Driver,
        classify: Callable[[NDArray[np.uint8]], Screen] = classify_screen,
        poll_sec: float = POLL_SEC,
        settle_polls: int = SETTLE_POLLS,
        collect_attempts: int = COLLECT_ATTEMPTS,
    ) -> None:
        self._driver = driver
        self._classify = classify
        self._poll_sec = poll_sec
        self._settle_polls = settle_polls
        self._collect_attempts = collect_attempts
        self.before: DiceSnapshot | None = None

    def arm(self) -> bool:
        """Roll の前に、盤に残っている出目(直前の出目)を記録する。読めれば True。

        読めなくても(ダイスが無い、視点が違う)、記録は空になるだけで、次の collect は動く。
        """
        snap, _ = self._settle()
        self.before = snap
        return snap is not None

    def refresh_before(self, image: NDArray[np.uint8]) -> None:
        """取得済みの 1 枚(メニューが出ている盤)から、Roll の前の出目を記録し直す。追加の取得はしない。

        `arm` は、静止の確認のために 2 枚以上取得する(1 枚 約 2 秒)。Roll の直前に取った 1 枚は、メニューが出ている
        (= ダイスは止まっている)ので、そのまま使える。メニューが出ていない・色が違う・ダイスが読めないときは、
        記録を変えない。
        """
        if self._classify(image).name not in MENU_SCREENS or not color_is_normal(image):
            return
        current = snapshot(image)
        if current is not None:
            self.before = current

    def collect(self) -> RollRead:
        """Roll の後に、今回の出目を返す。反映されていない、静止しない、視点が違う、のときは None と理由。"""
        reason = "未実行"
        for attempt in range(self._collect_attempts):
            snap, reason = self._settle()
            if snap is None:
                continue
            if self.before is not None and same_dice(self.before, snap):
                reason = "出目が Roll の前と同じ(Roll が反映されていない)"
                self._driver.sleep(self._poll_sec * (attempt + 1))
                continue
            self.before = snap  # 次の振り直し(ダブル)の比較元にする
            return RollRead(snap.values)
        return RollRead(None, reason)

    def _settle(self) -> tuple[DiceSnapshot | None, str]:
        """メニューが出ている視点で、連続 2 回同じ位置のダイスを返す。"""
        previous: DiceSnapshot | None = None
        reason = "取得していない"
        for _ in range(self._settle_polls):
            image = self._driver.io.capture().image
            screen = self._classify(image).name
            if screen not in MENU_SCREENS:
                previous, reason = None, f"メニューが出ていない({screen})"
            elif not color_is_normal(image):
                # 端末の色補正(夜間モードなど)で、盤の色が変わっている。色に頼る読み取りが誤るので、読まない
                previous, reason = None, "画面の色が通常と違う(端末の色補正の疑い)"
            else:
                current = snapshot(image)
                if current is None:
                    previous, reason = None, "ダイスが読めない"
                elif previous is not None and same_dice(previous, current):
                    return current, ""
                else:
                    previous, reason = current, "ダイスが静止しない"
            self._driver.sleep(self._poll_sec)
        return None, reason


ROLL_ATTEMPTS = (
    2  # 出目が動かないとき(Roll が反映されていないとき)に、送り直す回数の上限(最初の 1 回を含む)
)


@dataclass(frozen=True)
class RollOutcome:
    read: RollRead
    sent: int  # Roll を送った回数
    reason: str = ""


def roll_with_dice(driver: Driver, watcher: RollWatcher) -> RollOutcome:
    """Roll を送り、出目が動いたかで「反映された」を判断する。ダブルの振り直しを、取り違えて再送しない。

    `executor.roll` は、Roll 表示が残っていると「反映されていない」と見て再送する。ダブルでは、
    反映された後も Roll 表示が残るため、1 手番に 2 回振ってしまう(実機で位置が合わなくなった疑い)。
    ここでは、Roll の前後で出目の点が動いたかを基準にする。動いていなければ、反映されていない。
    Roll の前の出目は、最初に取る 1 枚から記録する(`arm` を呼んでいれば、それを上書きする)。画面が Roll 表示でなければ、何も送らない。
    """
    first = driver.io.capture().image
    if classify_screen(first).name != "board_my_turn_roll":
        return RollOutcome(RollRead(None, "Roll の画面ではない"), 0)
    watcher.refresh_before(
        first
    )  # この 1 枚が、Roll の前の出目(別に静止を確かめるための取得をしない)
    hold = HoldDrag(ex.ROLL_FROM, ex.ROLL_TO, ex.ROLL_HOLD_MS, ex.ROLL_STEPS, ex.ROLL_STEP_MS)
    sent = 0
    read = RollRead(None, "未実行")
    for _ in range(ROLL_ATTEMPTS):
        driver.sleep(ex.ROLL_SETTLE_SEC)
        driver.perform(hold)
        sent += 1
        driver.sleep(ex.ROLL_WAIT_SEC)
        read = watcher.collect()
        if read.values is not None:
            return RollOutcome(read, sent)
        if "メニューが出ていない" in read.reason:
            # カードなどが盤を覆っている。反映済みかもしれないので、送り直さない(閉じた後に collect し直す)
            return RollOutcome(read, sent, "結果の表示が割り込んだ")
    return RollOutcome(read, sent, "Roll が反映されない(上限まで再送)")
