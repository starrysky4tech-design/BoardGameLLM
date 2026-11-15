"""Roll の後の出目の取得(vision/roll_reader.py)のテスト。

実機の画面(datasets/eval/monopoly/roll_flow/、Git 管理外)の列を、偽の入出力で返して確かめる。
画面が無い環境では、実機の画面を使うテストを飛ばす。合成画像のテストは常に動く。
"""

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import pytest
from numpy.typing import NDArray

from bglm.core.models import Frame, InputAction
from bglm.plugins.monopoly.vision import roll_reader as rr
from bglm.plugins.monopoly.vision.executor import Driver
from bglm.plugins.monopoly.vision.screens import Screen

FLOW = Path("datasets/eval/monopoly/roll_flow")


def load(name: str) -> NDArray[np.uint8]:
    path = FLOW / f"{name}.png"
    if not path.exists():
        pytest.skip(f"実機の画面が無い: {path}")
    image = cv2.imread(str(path))
    assert image is not None
    return np.asarray(image, dtype=np.uint8)


class FakeIo:
    """画面の列を順に返す。列の最後は繰り返す。"""

    def __init__(self, frames: Sequence[NDArray[np.uint8]]) -> None:
        self._frames = list(frames)
        self.index = 0

    def capture(self) -> Frame:
        image = self._frames[min(self.index, len(self._frames) - 1)]
        self.index += 1
        return Frame.from_image(image, datetime(2026, 11, 5))

    def perform(self, action: InputAction) -> None:
        raise AssertionError("読み取りは入力を送らない")


def watcher(frames: Sequence[NDArray[np.uint8]], **kwargs: object) -> rr.RollWatcher:
    driver = Driver(io=FakeIo(frames), sleep=lambda _sec: None)
    return rr.RollWatcher(driver, **kwargs)  # type: ignore[arg-type]


# --- 実機の画面 ---


def test_new_roll_is_separated_from_the_previous_players_dice() -> None:
    # Roll 表示(盤に Dog の 6・3 が残る)で記録 → 自分が振る → 傾いた視点、カード、End Turn の順
    prompt, done = load("dog_roll_prompt"), load("my_roll_done")
    w = watcher([prompt, prompt, load("tilted_view"), load("card_dialog"), done, done])
    assert w.arm() is True
    assert w.before is not None and w.before.values == (6, 3)
    result = w.collect()
    assert result.values == (4, 5)
    assert result.total == 9


def test_unchanged_dice_means_the_roll_was_not_applied() -> None:
    prompt = load("dog_roll_prompt")
    w = watcher([prompt])
    w.arm()
    result = w.collect()
    assert result.values is None
    assert "Roll が反映されていない" in result.reason


def test_tilted_view_is_never_read() -> None:
    # 傾いた視点では、前の手番の 4・5 が読めてしまう。メニューが無いので、読まない
    w = watcher([load("tilted_view")])
    assert w.arm() is False
    result = w.collect()
    assert result.values is None
    assert "メニューが出ていない" in result.reason


def test_card_dialog_waits_and_can_be_collected_again() -> None:
    prompt, done = load("dog_roll_prompt"), load("my_roll_done")
    # 1 回目の collect: カードが閉じない → 失敗(理由つき)。呼び出し側がカードを閉じて、もう一度呼ぶ
    io_frames: list[NDArray[np.uint8]] = [prompt, prompt] + [load("card_dialog")] * 40
    w = watcher(io_frames)
    w.arm()
    first = w.collect()
    assert first.values is None and "メニューが出ていない" in first.reason
    assert w.before is not None and w.before.values == (6, 3)  # 記録は残る
    w2 = watcher([prompt, prompt, done, done])
    w2.arm()
    assert w2.collect().values == (4, 5)


def test_unstable_dice_are_not_returned() -> None:
    prompt, done = load("dog_roll_prompt"), load("my_roll_done")
    # 取得のたびに別の目(動いている)。連続 2 回同じ位置にならない
    frames = [prompt, prompt] + [done, prompt] * 40
    w = watcher(frames)
    w.arm()
    result = w.collect()
    assert result.values is None
    assert "静止しない" in result.reason


def test_doubles_reroll_is_compared_with_the_previous_roll() -> None:
    prompt, done = load("dog_roll_prompt"), load("my_roll_done")
    w = watcher([prompt, prompt, done, done, prompt, prompt])
    w.arm()
    assert w.collect().values == (4, 5)  # 1 回目(before は 6・3 から 4・5 へ更新)
    assert w.collect().values == (6, 3)  # 振り直し(前の 4・5 と違う)


# --- 合成画像(常に動く) ---

BOARD_MENU = Screen("board_my_turn_end", 1.0)


# 上の面の点の配置(面の中心からの相対位置、px)。test_dice.py と同じ作り
LAYOUT: dict[int, list[tuple[int, int]]] = {
    1: [(0, 0)],
    2: [(-6, -6), (6, 6)],
    3: [(-6, -6), (0, 0), (6, 6)],
    4: [(-6, -6), (6, -6), (-6, 6), (6, 6)],
    5: [(-6, -6), (6, -6), (0, 0), (-6, 6), (6, 6)],
    6: [(-6, -6), (6, -6), (-6, 0), (6, 0), (-6, 6), (6, 6)],
}


def synthetic(*dice_at: tuple[tuple[int, int], int]) -> NDArray[np.uint8]:
    image = np.full((1080, 2432, 3), (205, 230, 210), dtype=np.uint8)  # 盤の薄い緑
    for (cx, cy), value in dice_at:
        cv2.rectangle(image, (cx - 13, cy - 13), (cx + 13, cy + 25), (0, 0, 0), -1)
        for dx, dy in LAYOUT[value]:
            cv2.rectangle(
                image, (cx + dx - 2, cy + dy - 1), (cx + dx + 2, cy + dy + 1), (255, 255, 255), -1
            )
    return image


def test_same_dice_tolerates_noise_but_not_movement() -> None:
    a = rr.snapshot(synthetic(((1000, 450), 3), ((1300, 600), 5)))
    near = rr.snapshot(synthetic(((1001, 451), 3), ((1301, 599), 5)))
    moved = rr.snapshot(synthetic(((1030, 450), 3), ((1300, 600), 5)))
    assert a is not None and near is not None and moved is not None
    assert rr.same_dice(a, near)
    assert not rr.same_dice(a, moved)


def test_same_values_at_new_positions_are_a_new_roll() -> None:
    # 同じ 3・5 でも、位置が違えば別の Roll(同じ目が続いても、取りこぼさない)
    before = synthetic(((1000, 450), 3), ((1300, 600), 5))
    after = synthetic(((1060, 480), 3), ((1250, 640), 5))
    w = watcher([before, before, after, after], classify=lambda _img: BOARD_MENU)
    w.arm()
    assert w.collect().values == (3, 5)


# --- roll_with_dice: Roll を何回送るか ---


class RecordingIo(FakeIo):
    """入力を記録し、Roll(HoldDrag)を送るたびに、次の画面へ進む。"""

    def __init__(self, frames: Sequence[NDArray[np.uint8]]) -> None:
        super().__init__(frames)
        self.actions: list[InputAction] = []

    def perform(self, action: InputAction) -> None:
        self.actions.append(action)


def flow_driver(frames: Sequence[NDArray[np.uint8]]) -> tuple[Driver, RecordingIo]:
    io = RecordingIo(frames)
    return Driver(io=io, sleep=lambda _sec: None), io


def test_doubles_are_not_mistaken_for_an_unapplied_roll() -> None:
    # 1 回目の Roll で、出目が変わる(4・5)。メニューは Roll のまま(ダブルなら再び Roll が出る)。
    # executor.roll なら再送するが、roll_with_dice は出目が動いたので、1 回しか送らない
    prompt, done = load("dog_roll_prompt"), load("my_roll_done")
    dog_dice_then_new = [prompt, prompt, prompt, done, done, done, done]
    driver, io = flow_driver(dog_dice_then_new)
    watcher = rr.RollWatcher(driver, collect_attempts=1, settle_polls=3)
    watcher.arm()
    outcome = rr.roll_with_dice(driver, watcher)
    assert outcome.read.values == (4, 5)
    assert outcome.sent == 1
    assert len(io.actions) == 1


def test_unapplied_roll_is_resent_once_then_gives_up() -> None:
    prompt = load("dog_roll_prompt")
    driver, io = flow_driver([prompt])  # 出目が動かない
    watcher = rr.RollWatcher(driver, collect_attempts=1, settle_polls=3)
    watcher.arm()
    outcome = rr.roll_with_dice(driver, watcher)
    assert outcome.read.values is None
    assert outcome.sent == rr.ROLL_ATTEMPTS
    assert "反映されない" in outcome.reason


def test_card_interrupt_is_not_resent() -> None:
    prompt, card = load("dog_roll_prompt"), load("card_dialog")
    driver, io = flow_driver(
        [prompt, prompt, prompt, card]
    )  # arm 2 枚、画面確認 1 枚の後、カードが盤を覆う
    watcher = rr.RollWatcher(driver, collect_attempts=1, settle_polls=3)
    watcher.arm()
    outcome = rr.roll_with_dice(driver, watcher)
    assert outcome.read.values is None
    assert outcome.sent == 1
    assert outcome.reason == "結果の表示が割り込んだ"


def test_roll_is_refused_outside_the_roll_screen_and_sends_nothing() -> None:
    driver, io = flow_driver([load("my_roll_done")])  # End Turn 表示
    watcher = rr.RollWatcher(driver, collect_attempts=1, settle_polls=3)
    outcome = rr.roll_with_dice(driver, watcher)
    assert outcome.sent == 0 and io.actions == []


def test_is_doubles() -> None:
    assert rr.RollRead((3, 3)).is_doubles
    assert not rr.RollRead((3, 4)).is_doubles
    assert not rr.RollRead(None, "x").is_doubles


def test_tinted_screen_is_refused_with_a_clear_reason() -> None:
    done = load("my_roll_done")
    tinted = done.copy()
    tinted[..., 0] = np.clip(tinted[..., 0].astype(np.int16) + 8, 0, 255).astype(np.uint8)
    tinted[..., 2] = np.clip(tinted[..., 2].astype(np.int16) - 47, 0, 255).astype(np.uint8)
    w = watcher([tinted])
    assert w.arm() is False
    result = w.collect()
    assert result.values is None
    assert "画面の色が通常と違う" in result.reason


def test_roll_without_arm_takes_the_before_dice_from_the_first_capture() -> None:
    # arm(静止の確認で 2 枚以上取得)を呼ばない。最初の 1 枚が Roll の前の出目になる
    prompt, done = load("dog_roll_prompt"), load("my_roll_done")
    driver, io = flow_driver([prompt, done, done])
    watcher = rr.RollWatcher(driver, collect_attempts=1, settle_polls=3)
    outcome = rr.roll_with_dice(driver, watcher)
    assert outcome.read.values == (4, 5) and outcome.sent == 1
    # 取得: 最初の 1 枚 + 静止の確認 2 枚だけ(arm の 2 枚が要らない)
    assert io.index == 3


def test_refresh_before_ignores_a_tilted_view() -> None:
    driver, _io = flow_driver([load("dog_roll_prompt")])
    watcher = rr.RollWatcher(driver)
    watcher.refresh_before(load("tilted_view"))
    assert watcher.before is None  # メニューが出ていない画面は、記録しない
    watcher.refresh_before(load("dog_roll_prompt"))
    assert watcher.before is not None
