"""executor のテスト。画面名を台本どおりに返す偽の認識と、操作を記録する偽の入出力で、手 → 入力の列と、確認・停止の振る舞いを確かめる。

ダイスの位置は、実画面(290.png。あれば)から読む。
"""

import itertools
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import pytest

from bglm.core.models import Drag, Frame, HoldDrag, InputAction, Point
from bglm.plugins.wingspan.logic.cards import default_table
from bglm.plugins.wingspan.logic.goals import all_goal_tiles
from bglm.plugins.wingspan.logic.models import Food, Habitat, PlacedBird, Placement, PlayerBoard
from bglm.plugins.wingspan.logic.state import (
    AckConfirm,
    Decline,
    DrawCards,
    GainFood,
    GainFoodTask,
    LayEgg,
    LayEggs,
    LayEggsTask,
    PlayBird,
    Reroll,
    SkipPower,
    TakeDeck,
    TakeDie,
    TakeTray,
    TuckCard,
    WingspanState,
)
from bglm.plugins.wingspan.vision import layout
from bglm.plugins.wingspan.vision.executor import WingspanExecutor, press
from bglm.plugins.wingspan.vision.hand import card_point
from bglm.plugins.wingspan.vision.tracker import Tracker

F, G, W = Habitat.FOREST, Habitat.GRASSLAND, Habitat.WETLAND
DATA = Path("datasets/raw/wingspan/feasibility")
needs_real = pytest.mark.skipif(not (DATA / "290.png").exists(), reason="実画面が無い(Git 管理外)")


class ScriptedScreens:
    """画面名を、台本の順に返す(台本が尽きたら最後を繰り返す)。"""

    def __init__(self, names: list[str]) -> None:
        self._names = names
        self.calls = 0

    def screen_name(self, _image: object) -> str:
        name = self._names[min(self.calls, len(self._names) - 1)]
        self.calls += 1
        return name


class FakeIo:
    def __init__(self, image: np.ndarray | None = None) -> None:
        self.image = image if image is not None else np.zeros((1080, 2432, 3), dtype=np.uint8)
        self.actions: list[InputAction] = []

    def capture(self) -> Frame:
        return Frame.from_image(self.image, datetime(2026, 11, 14))

    def perform(self, action: InputAction) -> None:
        self.actions.append(action)


def executor(names: list[str], hand: list[str] | None = None) -> WingspanExecutor:
    ticks = itertools.count()
    return WingspanExecutor(
        recognizer=ScriptedScreens(names),  # type: ignore[arg-type]
        table=default_table(),
        sleep=lambda _s: None,
        clock=lambda: float(next(ticks)),
        hand_reader=(lambda _io, _n, _names: hand) if hand is not None else None,
    )


def board(
    forest=(), grass=(), wet=(), *, food=(0, 0, 0, 0, 0), hand=(), bonus=(), cubes=5
) -> PlayerBoard:  # type: ignore[no-untyped-def]
    return PlayerBoard(
        rows=(tuple(forest), tuple(grass), tuple(wet)),
        food=food,
        hand=hand,
        bonus=bonus,
        cubes=cubes,
    )


def state_with(mine: PlayerBoard, **changes) -> WingspanState:  # type: ignore[no-untyped-def]
    return replace(state_of(), players=(mine, PlayerBoard()), **changes)


def state_of(**changes) -> WingspanState:  # type: ignore[no-untyped-def]
    mine = PlayerBoard(
        rows=((PlacedBird("クロズキンアメリカムシクイ"),), (), ()),
        hand=("クロズキンアメリカムシクイ", "コマツグミ"),
        bonus=("草原管理者",),
        food=(2, 0, 0, 0, 0),
    )
    base = WingspanState(
        players=(mine, PlayerBoard()),
        to_move=0,
        first_player=0,
        round_index=0,
        feeder=("invertebrate", "rodent", "rodent"),
        tray=("ミサゴ", "", ""),
        deck=(),
        discard=(),
        goals=all_goal_tiles()[:4],
    )
    return replace(base, **changes)


def is_press(action: InputAction, x: int, y: int) -> bool:
    return isinstance(action, HoldDrag) and action.start == Point(x, y) == action.end


def test_gain_food_presses_the_next_forest_slot_and_expects_the_die_prompt() -> None:
    io = FakeIo()
    result = executor(["mat", "prompt:pick_die"]).execute(io, state_of(), GainFood())
    assert result.success
    x, y = layout.action_slot(F, 1)  # 森林に 1 羽 → 2 列目の枠
    assert len(io.actions) == 1 and is_press(io.actions[0], x, y)


def test_each_action_uses_its_own_row_and_prompt() -> None:
    for move, habitat, prompt in [
        (LayEggs(), G, "prompt:lay_eggs"),
        (DrawCards(), W, "prompt:pick_card"),
    ]:
        io = FakeIo()
        assert executor(["mat", prompt]).execute(io, state_of(), move).success
        x, y = layout.action_slot(habitat, 0)
        assert is_press(io.actions[0], x, y)


def test_refuses_to_start_unless_the_board_is_clear() -> None:
    for screen in ("prompt:lay_eggs", "habitat", "unknown"):
        io = FakeIo()
        result = executor([screen]).execute(io, state_of(), GainFood())
        assert not result.success and result.reason == f"unexpected_screen:{screen}"
        assert io.actions == []  # 入力を送らない


def test_never_presses_on_menus_even_mid_move() -> None:
    io = FakeIo()
    result = executor(["prompt:pick_die", "dialog:game_menu"]).execute(
        io, state_of(queue=(GainFoodTask(2),)), Decline()
    )
    # 最初の入力(確定)は通るが、次の入力の前にメニューが出ていれば止まる。Decline は 1 手 = 1 入力なので成功
    assert result.success and len(io.actions) == 1
    io2 = FakeIo()
    result2 = executor(["prompt:pick_die", "dialog:game_menu"]).execute(
        io2, state_of(), SkipPower()
    )
    # スキップの確認は、その画面が出たときだけ押す。メニューが出ているなら押さない(入力は 1 つだけ)
    assert result2.success and len(io2.actions) == 1


def test_resends_the_first_press_once_when_the_screen_did_not_change() -> None:
    io = FakeIo()
    # 1 回目の入力の後も盤のまま → 1 回だけ再送 → 案内が出る
    names = ["mat"] * 10 + ["prompt:pick_die"]
    result = executor(names).execute(io, state_of(), GainFood())
    assert result.success and len(io.actions) == 2 and io.actions[0] == io.actions[1]


def test_stops_without_a_third_attempt_when_the_screen_never_changes() -> None:
    io = FakeIo()
    result = executor(["mat"]).execute(io, state_of(), GainFood())
    assert not result.success and result.reason == "step_0_failed:mat"
    assert len(io.actions) == 2  # 最初の入力 + 再送 1 回だけ


def test_does_not_resend_when_the_screen_changed_to_something_unexpected() -> None:
    io = FakeIo()
    result = executor(["mat", "dialog:turn_start"]).execute(io, state_of(), GainFood())
    assert not result.success and len(io.actions) == 1  # 変わったので再送しない


@needs_real
def test_take_die_presses_the_panel_button_not_the_die_on_the_tray() -> None:
    # 290: 餌箱は 虫・ネズミ・ネズミ(上から)。盤のダイスではなく、パネルの下段のボタンを押す(中央寄せ、間隔 92)
    io = FakeIo(cv2.imread(str(DATA / "290.png")))
    state = state_of(queue=(GainFoodTask(1),))
    result = executor(["prompt:pick_die"]).execute(io, state, TakeDie(0, Food.INVERTEBRATE))
    assert result.success and len(io.actions) == 2
    assert is_press(io.actions[0], *layout.panel_die(0, 3))  # 上から 0 番目、3 個
    assert layout.panel_die(0, 3) == (1622, 980)
    assert is_press(io.actions[1], *layout.CONFIRM)  # 最後の 1 個なので確定


@needs_real
def test_take_die_does_not_confirm_while_more_dice_remain() -> None:
    io = FakeIo(cv2.imread(str(DATA / "290.png")))
    state = state_of(queue=(GainFoodTask(2),))
    result = executor(["prompt:pick_die"]).execute(io, state, TakeDie(1, Food.RODENT))
    assert result.success and len(io.actions) == 1
    assert is_press(io.actions[0], *layout.panel_die(1, 3))  # 最初のネズミ = 上から 1 番目


def test_panel_die_positions_split_the_panel_width_by_count() -> None:
    # 実測(RESULT.md §13): 1 個 1775、2 個 1665 / 1897(間隔 232)、5 個 1591 / 1684 / 1775 / 1868 / 1961(間隔 92)
    assert layout.panel_die(0, 1) == (1777, 980)
    two = [layout.panel_die(k, 2)[0] for k in range(2)]
    assert all(abs(got - want) <= 6 for got, want in zip(two, [1665, 1897], strict=True))
    five = [layout.panel_die(k, 5)[0] for k in range(5)]
    assert all(
        abs(got - want) <= 4 for got, want in zip(five, [1591, 1684, 1775, 1868, 1961], strict=True)
    )


@needs_real
def test_two_faced_die_opens_a_choice_window_and_picks_the_food() -> None:
    # 030_forest_action: 餌箱は 果実・種・種・虫/種・虫/種(上から)。虫/種のダイスで種を取る
    image = cv2.imread(str(DATA / "030_forest_action.png"))
    feeder = (
        "fruit",
        "invertebrate_or_seed",
        "invertebrate_or_seed",
        "seed",
        "seed",
    )  # logic の並び(昇順)
    state = state_of(feeder=feeder, queue=(GainFoodTask(1),))
    io = FakeIo(image)
    result = executor(["prompt:pick_die"]).execute(io, state, TakeDie(1, Food.SEED))
    assert result.success and len(io.actions) == 3
    assert is_press(io.actions[0], *layout.panel_die(3, 5))  # 上から 3 番目が最初の虫/種
    assert is_press(io.actions[1], *layout.TWO_FACED_CHOICE["seed"])  # 小窓で種
    assert is_press(io.actions[2], *layout.CONFIRM)


def test_missing_die_is_unsupported_not_guessed() -> None:
    state = state_of(feeder=("fish",), queue=(GainFoodTask(1),))
    io = FakeIo()  # 餌箱にダイスが写っていない
    result = executor(["prompt:pick_die"]).execute(io, state, TakeDie(0, Food.FISH))
    assert not result.success and result.reason == "unsupported:die_not_found:fish"
    assert io.actions == []


def test_lay_egg_presses_the_bird_and_confirms_after_the_last_egg() -> None:
    state = state_of(queue=(LayEggsTask(1),))
    io = FakeIo()
    assert executor(["prompt:lay_eggs"]).execute(io, state, LayEgg(Placement(F, 0))).success
    x0, y0, x1, y1 = layout.card_rect(F, 0)
    assert is_press(io.actions[0], (x0 + x1) // 2, (y0 + y1) // 2)
    assert is_press(io.actions[1], *layout.CONFIRM)
    io2 = FakeIo()
    executor(["prompt:lay_eggs"]).execute(
        io2, state_of(queue=(LayEggsTask(2),)), LayEgg(Placement(F, 0))
    )
    assert len(io2.actions) == 1  # まだ置く卵がある


def test_take_tray_and_deck_and_decline_and_reroll() -> None:
    io = FakeIo()
    assert executor(["prompt:pick_card"]).execute(io, state_of(), TakeTray(1)).success
    assert is_press(io.actions[0], layout.DRAW_TRAY_X[1], layout.DRAW_Y)
    assert is_press(io.actions[1], *layout.CONFIRM)
    io = FakeIo()
    assert executor(["prompt:pick_card"]).execute(io, state_of(), TakeDeck()).success
    assert is_press(io.actions[0], *layout.DRAW_DECK)
    io = FakeIo()
    assert executor(["prompt:pick_die"]).execute(io, state_of(), Reroll()).success
    assert is_press(io.actions[0], *layout.REROLL)
    io = FakeIo()
    assert executor(["prompt:discard_card"]).execute(io, state_of(), Decline()).success
    assert is_press(io.actions[0], *layout.CONFIRM)


def test_skip_power_confirms_then_accepts_the_skip_dialog() -> None:
    io = FakeIo()
    # 確定のボタンを押すと、スキップの確認ダイアログが出る(背景が暗くなる)。その「スキップ」を押す
    result = executor(["prompt:power_move", "confirm:skip", "confirm:skip"]).execute(
        io, state_of(), SkipPower()
    )
    assert result.success
    assert is_press(io.actions[0], *layout.CONFIRM)
    assert is_press(io.actions[1], *layout.SKIP_CONFIRM)


def test_play_bird_pays_exactly_the_chosen_food_through_the_change_panel() -> None:
    # 手札: ボーナス 1 + 鳥 2(クロズキン…、コマツグミ)= 3 枚。鳥の 1 枚目(添字 1)を森林の 2 列目へ。コスト: 虫 2
    state = state_of()
    move = PlayBird("クロズキンアメリカムシクイ", F, (2, 0, 0, 0, 0))
    io = FakeIo()
    # 画面の台本: 盤 → 支払い(drag の後)→ 支払い(require)→ 支払い(確定の前)→ … 要約の確定は、支払いのままなら送る
    names = ["mat", "prompt:pay_food", "prompt:pay_food", "prompt:pay_food", "prompt:pay_food"]
    assert (
        executor(names, hand=["草原管理者", "クロズキンアメリカムシクイ", "コマツグミ"])
        .execute(io, state, move)
        .success
    )
    drag = io.actions[0]
    assert isinstance(drag, Drag)
    assert (drag.start.x, drag.start.y) == card_point(3, 1)
    assert (drag.end.x, drag.end.y) == layout.action_slot(F, 1)
    assert is_press(io.actions[1], *layout.PAY_CHANGE)  # 既定に任せず、必ず「変更」を押す
    inv = layout.pay_food_button("invertebrate")
    assert is_press(io.actions[2], *inv) and is_press(io.actions[3], *inv)  # 虫を 2 回
    assert is_press(io.actions[4], *layout.CONFIRM) and is_press(io.actions[5], *layout.CONFIRM)


def test_summary_confirm_is_skipped_when_the_payment_screen_is_gone() -> None:
    state = state_of()
    move = PlayBird("クロズキンアメリカムシクイ", F, (2, 0, 0, 0, 0))
    io = FakeIo()
    names = ["mat", "prompt:pay_food", "prompt:pay_food", "prompt:pay_food", "mat"]
    assert (
        executor(names, hand=["草原管理者", "クロズキンアメリカムシクイ", "コマツグミ"])
        .execute(io, state, move)
        .success
    )
    assert len(io.actions) == 5  # 要約の確定は送らない(drag + 変更 + 虫 2 + 確定)


def test_play_bird_taps_the_slot_when_the_dragged_card_did_not_drop() -> None:
    # 実機: 札が持ち上がり、置ける枠が光ったまま盤に戻ることがある。光った置き先をタップすると置ける
    mine = board(wet=[PlacedBird("アメリカヤマセミ")], hand=("ミサゴ",), food=(0, 0, 1, 0, 0))
    move = PlayBird("ミサゴ", W, (0, 0, 1, 0, 0))
    io = FakeIo()
    names = ["mat", "mat", "prompt:pay_food", "prompt:pay_food", "prompt:pay_food", "mat"]
    assert executor(names).execute(io, state_with(mine), move).success
    assert isinstance(io.actions[0], Drag)
    assert is_press(io.actions[1], *layout.action_slot(W, 1))  # 置き先の再タップ
    assert is_press(io.actions[2], *layout.PAY_CHANGE)


def test_play_bird_pays_eggs_by_tapping_the_birds_after_the_food() -> None:
    mine = board(
        forest=[PlacedBird("クロズキンアメリカムシクイ", eggs=2)],
        grass=[PlacedBird("コマツグミ", eggs=1)],
        hand=("ミサゴ",),
        bonus=("草原管理者",),
        food=(0, 0, 3, 0, 0),
    )
    move = PlayBird("ミサゴ", W, (0, 0, 1, 0, 0), (Placement(F, 0), Placement(G, 0)))
    io = FakeIo()
    names = [
        "mat",
        "mat",
        "prompt:pay_food",
        "prompt:pay_food",
        "prompt:pay_eggs",
        "prompt:pay_eggs",
    ]
    assert executor(names).execute(io, state_with(mine), move).success
    x0, y0, x1, y1 = layout.card_rect(F, 0)
    gx0, gy0, gx1, gy1 = layout.card_rect(G, 0)
    taps = [a for a in io.actions if isinstance(a, HoldDrag)]
    assert is_press(taps[-3], (x0 + x1) // 2, (y0 + y1) // 2)  # 卵を払う 1 羽目
    assert is_press(taps[-2], (gx0 + gx1) // 2, (gy0 + gy1) // 2)  # 2 羽目
    assert is_press(taps[-1], *layout.CONFIRM)  # 最後に確定


def test_play_bird_stops_without_tapping_birds_if_the_egg_prompt_never_appears() -> None:
    mine = board(
        forest=[PlacedBird("クロズキンアメリカムシクイ", eggs=2)],
        hand=("ミサゴ",),
        food=(0, 0, 3, 0, 0),
    )
    move = PlayBird("ミサゴ", W, (0, 0, 1, 0, 0), (Placement(F, 0),))
    io = FakeIo()
    # 支払いの後、卵の案内が出ない(盤のまま)
    result = executor(["mat", "prompt:pay_food", "prompt:pay_food", "mat"]).execute(
        io, state_with(mine), move
    )
    assert not result.success and result.reason is not None
    x0, y0, x1, y1 = layout.card_rect(F, 0)
    bird = ((x0 + x1) // 2, (y0 + y1) // 2)
    assert not any(is_press(a, *bird) for a in io.actions)  # 案内が無いのに、盤の鳥を押さない


def test_play_bird_with_a_two_habitat_card_selects_the_habitat_first() -> None:
    # コマツグミは森林・草原の札。草原に置くなら、選択肢の右(草原)を押して確定する
    mine = board(hand=("コマツグミ",), bonus=("草原管理者",), food=(1, 0, 0, 0, 0))
    move = PlayBird("コマツグミ", G, (1, 0, 0, 0, 0))
    io = FakeIo()
    # drag の後に選択の画面、選択を押す前・確定を押す前も選択の画面、確定の後に支払いの画面(以降は支払いのまま)
    names = [
        "mat",
        "prompt:choose_habitat",
        "prompt:choose_habitat",
        "prompt:choose_habitat",
        "prompt:pay_food",
    ]
    assert executor(names).execute(io, state_with(mine), move).success
    assert is_press(io.actions[1], layout.HABITAT_CHOICE_XS[1], layout.HABITAT_CHOICE_Y)
    assert is_press(io.actions[2], *layout.CONFIRM)
    forest = PlayBird("コマツグミ", F, (1, 0, 0, 0, 0))
    io2 = FakeIo()
    executor(names).execute(io2, state_with(mine), forest)
    assert is_press(io2.actions[1], layout.HABITAT_CHOICE_XS[0], layout.HABITAT_CHOICE_Y)


def test_three_habitat_card_is_unsupported() -> None:
    mine = board(hand=("ヒメウタスズメ",), bonus=("草原管理者",), food=(1, 1, 0, 0, 0))
    result = executor(["mat"]).execute(
        FakeIo(), state_with(mine), PlayBird("ヒメウタスズメ", F, (1, 1, 0, 0, 0))
    )
    assert not result.success and result.reason == "unsupported:choose_habitat_3"


def test_unimplemented_moves_are_unsupported() -> None:
    result = executor(["mat"]).execute(FakeIo(), state_of(), TuckCard("コマツグミ"))
    assert not result.success and result.reason == "unsupported:TuckCard"


def test_press_is_a_hold_drag_with_the_same_start_and_end() -> None:
    action = press(10, 20)
    assert action.start == action.end and action.hold_ms == 250


def test_dialog_that_appears_after_observation_defers_the_move_without_input() -> None:
    # 観測では盤だったが、実行の直前に手番開始のダイアログが出た。入力を送らず、追跡も進めず、観測からやり直す
    tracker = Tracker()
    ticks = itertools.count()
    ex = WingspanExecutor(
        recognizer=ScriptedScreens(["dialog:turn_start"]),  # type: ignore[arg-type]
        table=default_table(),
        tracker=tracker,
        sleep=lambda _s: None,
        clock=lambda: float(next(ticks)),
    )
    io = FakeIo()
    result = ex.execute(io, state_of(), DrawCards())
    assert result.success and result.reason == "deferred:dialog:turn_start"
    assert io.actions == [] and tracker.state is None


def test_ack_confirm_picks_all_when_the_amount_is_asked() -> None:
    # 獲得の量を選ぶ能力: 確定するとスキップの確認が出る → 「スキップしない」→「全て獲得」→確定
    io = FakeIo()
    names = ["prompt:power_gain", "confirm:skip", "prompt:power_gain", "prompt:power_gain", "mat"]
    assert executor(names).execute(io, state_of(), AckConfirm()).success
    points = [(a.start.x, a.start.y) for a in io.actions if isinstance(a, HoldDrag)]
    assert points == [layout.CONFIRM, layout.SKIP_DECLINE, layout.GAIN_ALL, layout.CONFIRM]


def test_ack_confirm_is_a_single_press_when_no_amount_is_asked() -> None:
    io = FakeIo()
    assert (
        executor(["prompt:power_gain", "mat", "mat", "mat"])
        .execute(io, state_of(), AckConfirm())
        .success
    )
    assert len(io.actions) == 1


def test_hud_press_moves_by_the_measured_shift() -> None:
    # パネルのボタンは、測ったずれ(43px 左)だけ動かして押す。ずれが無ければ、基準の位置のまま
    ex = executor(["prompt:pick_die"])
    ex._dx = -43
    assert is_press(
        ex._hud_press(*layout.PAY_CHANGE), layout.PAY_CHANGE[0] - 43, layout.PAY_CHANGE[1]
    )
    ex._dx = 0
    assert is_press(ex._hud_press(*layout.PAY_CHANGE), *layout.PAY_CHANGE)


@needs_real
def test_plan_measures_the_shift_from_the_screen() -> None:
    # 452_now(左へ 43px ずれた対局)を見て計画すると、ずれが測られる。基準の画面(290)では 0
    shifted = executor(["prompt:pick_die"])
    shifted._plan(FakeIo(cv2.imread(str(DATA / "452_now.png"))), state_of(), Decline())
    assert shifted._dx == -43
    normal = executor(["prompt:pick_die"])
    normal._plan(FakeIo(cv2.imread(str(DATA / "290.png"))), state_of(), Decline())
    assert normal._dx == 0


def test_single_habitat_card_confirms_when_the_habitat_is_asked() -> None:
    # 生息地が 1 つの札でも、置く生息地を聞かれることがある。置いた先に✓が付いているので、確定だけで先へ進む
    mine = board(wet=[PlacedBird("アメリカヤマセミ")], hand=("ミサゴ",), food=(0, 0, 1, 0, 0))
    move = PlayBird("ミサゴ", W, (0, 0, 1, 0, 0))
    io = FakeIo()
    names = [
        "mat",
        "prompt:choose_habitat",
        "prompt:choose_habitat",
        "prompt:pay_food",
        "prompt:pay_food",
        "mat",
    ]
    assert executor(names).execute(io, state_with(mine), move).success
    points = [(a.start.x, a.start.y) for a in io.actions if isinstance(a, HoldDrag)]
    assert points[0] == layout.CONFIRM  # ドラッグの次が、生息地の確認(置く先の再タップは要らない)


def test_play_bird_uses_the_actual_hand_order_not_the_tracked_one() -> None:
    # 実機: 追跡は (ボーナス、クロズキン…、ミサゴ)、実際の並びは (ボーナス、ミサゴ、クロズキン…)。実際の並びの位置を押す
    mine = board(
        hand=("クロズキンアメリカムシクイ", "ミサゴ"), bonus=("草原管理者",), food=(0, 0, 3, 0, 0)
    )
    move = PlayBird("ミサゴ", W, (0, 0, 1, 0, 0))
    io = FakeIo()
    names = ["mat", "prompt:pay_food", "prompt:pay_food", "prompt:pay_food", "prompt:pay_food"]
    actual = ["草原管理者", "ミサゴ", "クロズキンアメリカムシクイ"]  # 実際は ミサゴ が 鳥の 1 番目
    assert executor(names, hand=actual).execute(io, state_with(mine), move).success
    drag = io.actions[0]
    assert isinstance(drag, Drag)
    assert (drag.start.x, drag.start.y) == card_point(3, 1)  # 追跡の順なら card_point(3, 2) だった


def test_play_bird_stops_when_the_hand_does_not_match() -> None:
    state = state_of()
    move = PlayBird("コマツグミ", F, (1, 0, 0, 0, 0))
    io = FakeIo()
    other = ["草原管理者", "ミサゴ", "コマツグミ"]  # 追跡と札が違う(引いた札を見落とした)
    result = executor(["mat"], hand=other).execute(io, state, move)
    assert (
        not result.success
        and result.reason is not None
        and result.reason.startswith("hand_mismatch")
    )
    assert io.actions == []
