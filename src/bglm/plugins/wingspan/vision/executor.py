"""Wingspan の手を、入力の列に変えて実行する(docs/02「MoveExecutor」、02_DESIGN.md 論点 7)。

1 つの手を、押下(タップ)とドラッグの列に展開し、各入力の後に画面を取り直して、期待した画面(案内の種類など)に
変わったかを確かめる。**変わらなければ再実行せず止まる**(最初の入力だけ、画面が変わっていなければ 1 回だけ再送する)。

- 入力は押下方式(保持 250 ms の HoldDrag)。`input tap` は効かないことがあった(RESULT.md §11)
- 札の移動は、1.5 秒のドラッグ(`input swipe`)。実機で確認済み
- 押してよいのは、自分の手番の全体ボード(案内パネルの有無は問わない)だけ。メニューやダイアログのときは入力しない
- 対応する手: 行動の選択(餌・産卵・札を引く)、ダイスを取る、卵を置く、札を取る(トレイ・山札)、振り直し、
  任意の変換をしない(Decline)、能力のスキップ、鳥のプレイ。**それ以外は "unsupported" で止まる**
  (2 種の目のダイス、複数の生息地の札、札を払う・卵を払う変換、差し込み、初期選択は、実機で位置を測ってから足す)
- 鳥のプレイは、餌の払い方をアプリの既定のままにする(払い方の変更は未対応)。実行後に画面から読み直した餌の数が、
  手の `spend` と違えば、認識(recognizer)が画面の値で追跡を直す
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, replace

from bglm.core.models import Drag, ExecutionResult, HoldDrag, InputAction, Point
from bglm.core.protocols import GameIo
from bglm.plugins.wingspan.logic.cards import CardTable, default_table
from bglm.plugins.wingspan.logic.models import (
    FOODS,
    INV_OR_SEED,
    UNKNOWN_CARD,
    Food,
    Habitat,
    Placement,
)
from bglm.plugins.wingspan.logic.rules import WingspanRules
from bglm.plugins.wingspan.logic.state import (
    AckConfirm,
    AckMatView,
    AckRound,
    AckSkip,
    AckTurnStart,
    Decline,
    DrawCards,
    DrawTask,
    GainFood,
    GainFoodTask,
    KeepSetup,
    LayEgg,
    LayEggs,
    LayEggsTask,
    Move,
    PlayBird,
    Reroll,
    SkipPower,
    TakeDeck,
    TakeDie,
    TakeTray,
    WingspanState,
)
from bglm.plugins.wingspan.vision import layout
from bglm.plugins.wingspan.vision.counters import hud_shift
from bglm.plugins.wingspan.vision.feeder import read_feeder
from bglm.plugins.wingspan.vision.hand import card_point
from bglm.plugins.wingspan.vision.hand_reader import read_hand_names
from bglm.plugins.wingspan.vision.prompt import PromptKind
from bglm.plugins.wingspan.vision.recognizer import KNOWN_BONUS_NAMES, WingspanRecognizer
from bglm.plugins.wingspan.vision.tracker import Tracker

PRESS_HOLD_MS = 250
DRAG_MS = 1500
POLL_SEC = 1.0
WAIT_SEC = 8.0
DECK_ANIMATION_SEC = 6.0  # 山札から引いた後は、演出の間(約 5 秒)確定が効かない(RESULT.md §9)
TURN_START_AT = (1216, 650)  # 手番開始のダイアログ(中央)を押す位置
FORBIDDEN_SCREENS = ("dialog:game_menu", "dialog:store", "unknown")
SKIP_CONFIRM_SCREEN = "confirm:skip"

# 行動を選べる画面(何も重ならない盤)と、決定に答える画面(案内パネルが出ている盤。案内の種類は問わない)
ACTION_SCREENS = ("mat",)
# 観測の直後に出ることがある、待てば進む画面(手番開始・ラウンドの採点のダイアログ、相手の手番)
DEFERRING_SCREENS = ("dialog:turn_start", "dialog:round_score", "opponent_turn")
DECISION_SCREENS = tuple(f"prompt:{kind.value}" for kind in PromptKind)


def press(x: int, y: int) -> HoldDrag:
    return HoldDrag(Point(x, y), Point(x, y), hold_ms=PRESS_HOLD_MS, steps=1, step_ms=0)


def drag(start: tuple[int, int], end: tuple[int, int]) -> Drag:
    return Drag(Point(*start), Point(*end), DRAG_MS)


@dataclass(frozen=True)
class Step:
    action: InputAction
    expect: frozenset[str] | None = None  # 入力の後に出てよい画面名。None なら確かめない
    pause: float = 0.0  # 入力の後、画面を見る前の待ち
    only_on: frozenset[str] | None = (
        None  # 入力の前の画面がこの中のときだけ送る(外なら、この入力を飛ばす)
    )
    require: frozenset[str] | None = (
        None  # 入力の前に、この中のどれかの画面になるまで待つ(ならなければ止まる)
    )


class UnsupportedError(Exception):
    """この手はまだ実機で位置を測っていない。"""


HandReader = Callable[
    [GameIo, int, list[str]], list[str] | None
]  # 手札(ボーナスを含む)の札名を左から読む


class WingspanExecutor:
    def __init__(
        self,
        recognizer: WingspanRecognizer | None = None,
        table: CardTable | None = None,
        tracker: Tracker | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        hand_reader: HandReader | None = None,
    ) -> None:
        self._recognizer = recognizer or WingspanRecognizer()
        self._table = table or default_table()
        self._rules = WingspanRules(self._table)
        self._tracker = tracker
        self._sleep = sleep
        self._clock = clock
        self._hand_reader = hand_reader or self._read_hand

    def execute(self, io: GameIo, state: WingspanState, move: Move) -> ExecutionResult:
        actions: list[InputAction] = []
        if isinstance(move, PlayBird):
            fixed = self._verify_hand(io, state, move)
            if isinstance(fixed, ExecutionResult):
                return fixed
            state = fixed
        try:
            steps = self._plan(io, state, move)
        except UnsupportedError as exc:
            return ExecutionResult(False, f"unsupported:{exc}")
        starts_action = isinstance(move, GainFood | LayEggs | DrawCards | PlayBird)
        allowed = ACTION_SCREENS if starts_action else DECISION_SCREENS
        if isinstance(move, KeepSetup):
            allowed = ("setup:keep",)
        elif isinstance(move, AckTurnStart):
            allowed = ("dialog:turn_start",)
        elif isinstance(move, AckRound):
            allowed = ("dialog:round_score",)
        elif isinstance(move, AckMatView):
            allowed = ("habitat",)
        for index, step in enumerate(steps):
            if step.require is not None:
                before = self._wait(io, step.require)
                if before not in step.require:
                    return ExecutionResult(False, f"required_screen:{before}", tuple(actions))
            else:
                before = self._screen(io) if index == 0 else self._settled(io)
            if step.only_on is not None and before not in step.only_on:
                continue  # 条件の画面でなければ、この入力は要らない(例: 払い方の要約の確定)
            if index == 0 and before in DEFERRING_SCREENS and before not in allowed:
                # 観測の後に、手番開始のダイアログなどが出た(観測と実行の間の競合)。入力は送らず、観測からやり直す。
                # 手は実行していないので、追跡の状態は進めない
                return ExecutionResult(True, f"deferred:{before}")
            if before in FORBIDDEN_SCREENS or (index == 0 and before not in allowed):
                return ExecutionResult(False, f"unexpected_screen:{before}", tuple(actions))
            io.perform(step.action)
            actions.append(step.action)
            if step.pause:
                self._sleep(step.pause)
            if step.expect is None:
                continue
            after = self._wait(io, step.expect)
            if after not in step.expect and index == 0 and after == before:
                io.perform(
                    step.action
                )  # 画面が変わらなかったときだけ、最初の入力を 1 回だけ再送する
                actions.append(step.action)
                after = self._wait(io, step.expect)
            if after not in step.expect:
                return ExecutionResult(False, f"step_{index}_failed:{after}", tuple(actions))
        if self._tracker is not None:
            self._tracker.state = self._rules.apply(
                state, move
            )  # 実行できた手の予測を、次の観測の土台にする
        return ExecutionResult(True, actions=tuple(actions))

    def _read_hand(self, io: GameIo, count: int, names: list[str]) -> list[str] | None:
        return read_hand_names(io, count, self._recognizer.reader(), names, self._sleep)

    def _verify_hand(
        self, io: GameIo, state: WingspanState, move: PlayBird
    ) -> WingspanState | ExecutionResult:
        """札を出す前に、手札の実際の並びを読んで、追跡の手札の順を直す。

        アプリの手札は、引いた札を追跡の順(末尾)に置くとは限らない(実機: 追跡 ヤブガラ → アカハシ、実際は アカハシ → ヤブガラ。
        取り違えて、別の札を出した)。札を出す位置は並びの何番目かで決まるので、押す前に読んで確かめる。同じ名前の札だけなら、
        位置が決まらなくても取り違えない。
        """
        board = state.players[state.to_move]
        if len(set(board.hand)) <= 1:
            return state  # 全て同じ名前なら、どれを押しても同じ札
        names = [*self._table.birds, *KNOWN_BONUS_NAMES]
        count = len(board.bonus) + len(board.hand)
        read = self._hand_reader(io, count, names)
        if read is None:
            return ExecutionResult(False, "hand_zoom_stuck")
        actual = tuple(read[len(board.bonus) :])
        known = tuple(c for c in actual if c != UNKNOWN_CARD)
        if sorted(known) != sorted(c for c in board.hand if c != UNKNOWN_CARD):
            return ExecutionResult(False, f"hand_mismatch:{actual}")
        if UNKNOWN_CARD in actual:
            return ExecutionResult(
                False, f"hand_unreadable:{actual}"
            )  # 読めない札があると、位置が確かでない
        if actual == board.hand:
            return state
        return state.with_player(state.to_move, replace(board, hand=actual))

    # ---- 画面 ----

    def _screen(self, io: GameIo) -> str:
        return self._recognizer.screen_name(io.capture().image)

    def _settled(self, io: GameIo) -> str:
        """画面が遷移中(unknown)の間は、落ち着くまで待つ。ずっと unknown なら unknown を返す(呼び出し側が止める)。"""
        deadline = self._clock() + WAIT_SEC
        name = self._screen(io)
        while name == "unknown" and self._clock() < deadline:
            self._sleep(POLL_SEC)
            name = self._screen(io)
        return name

    def _wait(self, io: GameIo, expect: frozenset[str]) -> str:
        deadline = self._clock() + WAIT_SEC
        name = self._screen(io)
        while name not in expect and self._clock() < deadline:
            self._sleep(POLL_SEC)
            name = self._screen(io)
        return name

    # ---- 手 → 入力の列 ----

    def _plan(self, io: GameIo, state: WingspanState, move: Move) -> list[Step]:
        # 描画が左右にずれる対局がある(実機: 左右のパネルが 43px 左へ)。パネルのボタンは、そのずれだけ動かして押す
        self._dx = hud_shift(io.capture().image)
        board = state.players[state.to_move]
        match move:
            case GainFood():
                return [
                    self._slot(Habitat.FOREST, len(board.row(Habitat.FOREST)), PromptKind.PICK_DIE)
                ]
            case LayEggs():
                return [
                    self._slot(
                        Habitat.GRASSLAND, len(board.row(Habitat.GRASSLAND)), PromptKind.LAY_EGGS
                    )
                ]
            case DrawCards():
                return [
                    self._slot(
                        Habitat.WETLAND, len(board.row(Habitat.WETLAND)), PromptKind.PICK_CARD
                    )
                ]
            case TakeDie(index=i, food=food):
                return self._take_die(io, state, i, food)
            case LayEgg(at=at):
                return self._lay_egg(state, at)
            case TakeTray(index=i):
                steps = [Step(press(layout.DRAW_TRAY_X[i], layout.DRAW_Y), pause=1.0)]
                return steps + self._confirm_draw(state)
            case TakeDeck():
                steps = [Step(press(*layout.DRAW_DECK), pause=DECK_ANIMATION_SEC)]
                return steps + self._confirm_draw(state)
            case Reroll():
                return [Step(press(*layout.REROLL), pause=3.0)]
            case Decline():
                return [Step(press(*layout.CONFIRM), pause=2.0)]
            case SkipPower():
                # 確認ダイアログ(スキップ)が出ない案内もある(矢印を押すだけで進む)ので、出たときだけ押す
                return [
                    Step(press(*layout.CONFIRM), pause=1.5),
                    Step(
                        press(*layout.SKIP_CONFIRM),
                        pause=2.0,
                        only_on=frozenset({"confirm:skip"}),
                    ),
                ]
            case PlayBird():
                return self._play_bird(state, move)
            case KeepSetup():
                return self._keep_setup(state, move)
            case AckTurnStart():
                return [Step(press(*TURN_START_AT), pause=3.0)]
            case AckRound():
                return [Step(press(*layout.CONFIRM), pause=3.0)]
            case AckConfirm():
                # 獲得の量を選ぶ能力は、量を選ばずに確定するとスキップの確認が出る。出たときだけ、「スキップしない」→
                # 「全て獲得」→確定にする(出なければ、最初の確定だけで済んだ)
                skip = frozenset({SKIP_CONFIRM_SCREEN})
                return [
                    Step(press(*layout.CONFIRM), pause=2.0),
                    Step(press(*layout.SKIP_DECLINE), pause=1.5, only_on=skip),
                    Step(
                        self._hud_press(*layout.GAIN_ALL),
                        pause=1.5,
                        only_on=frozenset({"prompt:power_gain"}),
                    ),
                    Step(
                        press(*layout.CONFIRM), pause=3.0, only_on=frozenset({"prompt:power_gain"})
                    ),
                ]
            case AckMatView():
                return [Step(press(*layout.MAT_BUTTON), expect=frozenset({"mat"}), pause=2.0)]
            case AckSkip():
                return self._plan(io, state, SkipPower())
        raise UnsupportedError(type(move).__name__)

    _dx = 0  # 直近の _plan で測った、パネルの横のずれ

    def _hud_press(self, x: int, y: int) -> HoldDrag:
        return press(x + self._dx, y)

    @staticmethod
    def _slot(habitat: Habitat, birds: int, prompt: PromptKind) -> Step:
        x, y = layout.action_slot(habitat, birds)
        return Step(press(x, y), expect=frozenset({f"prompt:{prompt.value}"}), pause=1.0)

    def _take_die(self, io: GameIo, state: WingspanState, index: int, food: Food) -> list[Step]:
        """餌の選択パネルの下段のダイスのボタンを押す(盤の餌箱のダイスは押しても選べない)。"""
        face = state.feeder[index]
        dice = read_feeder(io.capture().image)  # 上から順 = パネルの並び順
        ranks = [i for i, d in enumerate(dice) if d.face == face]
        if not ranks:
            raise UnsupportedError(f"die_not_found:{face}")
        steps = [Step(self._hud_press(*layout.panel_die(ranks[0], len(dice))), pause=1.5)]
        if face == INV_OR_SEED:  # 2 種の目: 小窓で、取る餌を選ぶ
            choice = layout.TWO_FACED_CHOICE.get(food.value)
            if choice is None:
                raise UnsupportedError(f"two_faced_choice:{food.value}")
            steps.append(Step(self._hud_press(*choice), pause=1.5))
        task = state.queue[0] if state.queue else None
        board = state.players[state.to_move]
        # 最後の 1 個を取ったら確定。ただし、札を捨てて餌を足せるとき(変換)は、変換の決定(Decline)が確定を担う
        if (
            isinstance(task, GainFoodTask)
            and task.remaining == 1
            and not (task.convert and board.hand)
        ):
            steps.append(Step(press(*layout.CONFIRM), pause=2.0))
        return steps

    @staticmethod
    def _lay_egg(state: WingspanState, at: Placement) -> list[Step]:
        x0, y0, x1, y1 = layout.card_rect(at.habitat, at.index)
        steps = [Step(press((x0 + x1) // 2, (y0 + y1) // 2), pause=1.2)]
        task = state.queue[0] if state.queue else None
        board = state.players[state.to_move]
        # 最後の 1 個を置いたら確定。ただし、餌を払って卵を足せるとき(変換)は、変換の決定(Decline)が確定を担う
        if (
            isinstance(task, LayEggsTask)
            and task.remaining == 1
            and not (task.bonus and sum(board.food) > 0)
        ):
            steps.append(Step(press(*layout.CONFIRM), pause=2.0))
        return steps

    @staticmethod
    def _confirm_draw(state: WingspanState) -> list[Step]:
        """札を引く: 最後の 1 枚で、卵を捨てて札を足せる(変換)ときは確定しない。まだ引く札が残るときも確定しない。"""
        task = state.queue[0] if state.queue else None
        board = state.players[state.to_move]
        if isinstance(task, DrawTask):
            has_egg = any(board.bird_at(p).eggs > 0 for p in board.placements())
            if task.remaining > 1 or (task.bonus and has_egg):
                return []
        return [Step(press(*layout.CONFIRM), pause=2.0)]

    def supports(self, state: WingspanState, move: Move) -> bool:
        """この手を、実機で実行できるか(位置を測った手か)。思考がこの手だけから選ぶために使う。"""
        match move:
            case PlayBird():
                return len(self._table.bird(move.card).habitats) <= 2  # 3 択の生息地の選択は未測定
            case (
                GainFood()
                | LayEggs()
                | DrawCards()
                | TakeDie()
                | LayEgg()
                | TakeTray()
                | TakeDeck()
                | Reroll()
                | Decline()
                | SkipPower()
                | AckTurnStart()
                | AckConfirm()
                | AckSkip()
                | AckRound()
                | AckMatView()
                | KeepSetup()
            ):
                return True
        return False

    @staticmethod
    def _keep_setup(state: WingspanState, move: KeepSetup) -> list[Step]:
        """初期選択: 鳥(左からの位置)と餌を押し、確定。続くボーナスの画面で、左の札を選んで確定する。"""
        board = state.players[state.to_move]
        if len(move.birds) + len(move.foods) != 5:
            raise UnsupportedError("setup_count")
        used: set[int] = set()
        steps: list[Step] = []
        for name in move.birds:
            index = next((i for i, h in enumerate(board.hand) if h == name and i not in used), None)
            if index is None:
                raise UnsupportedError("setup_card_missing")
            used.add(index)
            steps.append(Step(press(layout.SETUP_CARD_X[index], layout.SETUP_CARD_Y), pause=0.8))
        for food in move.foods:
            x = layout.SETUP_FOOD_X[layout.FOOD_ORDER_ON_SCREEN.index(food.value)]
            steps.append(Step(press(x, layout.SETUP_FOOD_Y), pause=0.8))
        bonus = frozenset({"setup:bonus"})
        steps.append(Step(press(*layout.CONFIRM), expect=bonus, pause=2.5))
        index = board.bonus.index(move.bonus)
        steps.append(Step(press(layout.SETUP_BONUS_X[index], layout.SETUP_BONUS_Y), pause=1.0))
        steps.append(Step(press(*layout.CONFIRM), pause=4.0))
        return steps

    def _play_bird(self, state: WingspanState, move: PlayBird) -> list[Step]:
        """鳥のプレイ(RESULT.md §9〜§16): 札をドラッグ → (生息地の選択)→ 払い方を「変更」で指定 → 確定 → 卵を払う鳥をタップ → 確定。

        払い方は、アプリの既定に任せず、必ず「変更」で logic の `spend` どおりに指定する(既定が一致する保証が無いため)。
        """
        board = state.players[state.to_move]
        options = sorted(self._table.bird(move.card).habitats, key=lambda h: h.value)
        count = len(board.bonus) + len(board.hand)
        start = card_point(count, len(board.bonus) + board.hand.index(move.card))
        target = layout.action_slot(move.habitat, len(board.row(move.habitat)))
        pay = frozenset({f"prompt:{PromptKind.PAY_FOOD.value}"})
        steps: list[Step] = []
        # ドラッグで札が持ち上がっても、置き先に落ちないことがある(実機: 札が持ち上がり、置ける枠が光ったまま盤に戻る)。
        # そのときは、光った置き先をタップすると置ける。次の案内が出ていなければ(盤のままなら)、置き先を 1 回タップする
        retry = Step(press(*target), only_on=frozenset({"mat"}), pause=2.0)
        if len(options) == 1:
            steps.append(Step(drag(start, target), pause=2.0))
            steps.append(retry)
            # 生息地が 1 つの札でも、置く生息地を聞かれることがある(実機)。置いた先に✓が付いているので、確定だけで進む
            asked = frozenset({f"prompt:{PromptKind.CHOOSE_HABITAT.value}"})
            steps.append(Step(press(*layout.CONFIRM), only_on=asked, expect=pay, pause=2.0))
        else:
            choose = frozenset({f"prompt:{PromptKind.CHOOSE_HABITAT.value}"})
            if len(options) != 2:
                raise UnsupportedError("choose_habitat_3")  # 3 択の位置は未測定
            x = layout.HABITAT_CHOICE_XS[options.index(move.habitat)]
            steps.append(Step(drag(start, target), pause=2.0))
            steps.append(retry)
            steps.append(
                Step(self._hud_press(x, layout.HABITAT_CHOICE_Y), pause=1.0, require=choose)
            )
            steps.append(Step(press(*layout.CONFIRM), expect=pay, pause=2.0))
        steps.append(Step(self._hud_press(*layout.PAY_CHANGE), pause=1.5, require=pay))
        for food, n in zip(FOODS, move.spend, strict=True):
            steps += [
                Step(self._hud_press(*layout.pay_food_button(food.value)), pause=0.8)
                for _ in range(n)
            ]
        steps.append(Step(press(*layout.CONFIRM), pause=2.0))
        # 払い方の要約が出ていれば、もう一度確定する(出ていなければ、この入力は飛ばす)
        steps.append(Step(press(*layout.CONFIRM), pause=2.0, only_on=pay))
        if move.egg_from:
            eggs = frozenset({f"prompt:{PromptKind.PAY_EGGS.value}"})
            for k, at in enumerate(move.egg_from):
                x0, y0, x1, y1 = layout.card_rect(at.habitat, at.index)
                tap = press((x0 + x1) // 2, (y0 + y1) // 2)
                steps.append(Step(tap, pause=1.2, require=eggs if k == 0 else None))
            steps.append(Step(press(*layout.CONFIRM), pause=2.5))
        return steps
