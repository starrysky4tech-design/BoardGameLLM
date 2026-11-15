"""Wingspan の認識。1 枚の画面から、画面種別と(読めるときは)状態を決める(docs/02「Recognizer」)。

方針:
- **盤を読むのは、何も重ならない全体ボード(MAT で案内パネルが無い)だけ**。自分の手番かどうかは、砂時計が無いことで決める
  (確定の約 1.2 秒後に砂時計、約 2.4 秒後に手番開始のダイアログが出る。実機の観測)
- 読んだ結果は、追跡している状態(previous)と照合する。鳥の名前が食い違う、鳥が減る、キューブが増える(ラウンドの切り替わり以外)
  ときは、状態を採用せず UNKNOWN にして止める(推測で埋めない)
- 山札・捨て札・相手の手札・目的は画面から読めない。直前の状態から引き継ぐ。**直前の状態が無い最初の観測は、状態を作らない**
  (目的とラウンドは別の画面で読む。`scripts/wingspan/` の再開の道具が最初の状態を作る)
- 案内パネルが出ている画面は、直前の状態をそのまま返し、案内の種類を画面名に入れる(決定の種類との照合は呼び出し側)
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, replace

import cv2
import numpy as np
from numpy.typing import NDArray

from bglm.core.models import Frame, Point, Recognition, Tap, UiKind, UiState
from bglm.core.protocols import GameIo
from bglm.plugins.wingspan.logic.board import TURNS_PER_ROUND
from bglm.plugins.wingspan.logic.board import TURNS_PER_ROUND as _TURNS
from bglm.plugins.wingspan.logic.cards import CardTable, default_table
from bglm.plugins.wingspan.logic.goals import GoalTile
from bglm.plugins.wingspan.logic.helpers import eggable
from bglm.plugins.wingspan.logic.models import HABITATS, UNKNOWN_CARD, PlacedBird, PlayerBoard
from bglm.plugins.wingspan.logic.rounds import end_round
from bglm.plugins.wingspan.logic.state import (
    DrawTask,
    GainFoodTask,
    LayEggsTask,
    SetupTask,
    Task,
    WingspanState,
)
from bglm.plugins.wingspan.vision import layout
from bglm.plugins.wingspan.vision.badges import BadgeKind
from bglm.plugins.wingspan.vision.board_reader import BirdRead, MatRead, read_mat
from bglm.plugins.wingspan.vision.dialogs import (
    DIALOG_SCALE,
    DialogKind,
    SetupKind,
    is_skip_confirm,
    parse_turn_header,
    read_dialog,
    read_setup,
)
from bglm.plugins.wingspan.vision.digits import Glyph
from bglm.plugins.wingspan.vision.feeder import feeder_faces
from bglm.plugins.wingspan.vision.hand_reader import read_hand_names
from bglm.plugins.wingspan.vision.mat import Image, LineReader
from bglm.plugins.wingspan.vision.names import match_name
from bglm.plugins.wingspan.vision.ocr import japanese_reader
from bglm.plugins.wingspan.vision.prompt import PromptKind, expected_prompts, read_prompt
from bglm.plugins.wingspan.vision.screens import ScreenKind, classify, is_toast
from bglm.plugins.wingspan.vision.tracker import Tracker
from bglm.plugins.wingspan.vision.tray import draw_screen_tray
from bglm.plugins.wingspan.vision.viewing import Viewing, opponent_is_playing, viewing

LOW_CONFIDENCE = 0.3  # 照合で問題があったときの確信度(閾値未満)


def _unknown(screen: str, *problems: str) -> Recognition[WingspanState]:
    return Recognition(UiState(UiKind.UNKNOWN, screen), None, 0.0, problems)


def _placed(read: BirdRead, previous: PlacedBird | None) -> PlacedBird:
    """画面の 1 羽を、追跡の 1 羽に直す。読めない札名は、追跡の名前を引き継ぐ(推測で変えない)。"""
    name = read.name
    if name == UNKNOWN_CARD and previous is not None:
        name = previous.name
    badge = read.badge
    cached = badge.count or 0 if badge and badge.kind is BadgeKind.CACHED else 0
    tucked = badge.count or 0 if badge and badge.kind is BadgeKind.TUCKED else 0
    used = previous.used if previous is not None else False
    return PlacedBird(name, read.eggs, cached, tucked, used)


def merge_board(previous: PlayerBoard, read: MatRead) -> tuple[PlayerBoard, tuple[str, ...]]:
    """画面の盤を、追跡の盤へ反映する。食い違いがあれば、その名前を返す(盤は呼び出し側が捨てる)。"""
    problems: list[str] = []
    board = previous
    for habitat in HABITATS:
        before = previous.row(habitat)
        seen = read.rows[habitat]
        if len(seen) < len(before):
            problems.append(f"birds_decreased:{habitat.value}")
            continue
        row: list[PlacedBird] = []
        for i, bird in enumerate(seen):
            old = before[i] if i < len(before) else None
            merged = _placed(bird, old)
            if (
                old is not None
                and old.name != UNKNOWN_CARD
                and bird.name
                not in (
                    UNKNOWN_CARD,
                    old.name,
                )
            ):
                problems.append(f"bird_mismatch:{habitat.value}[{i}]")
            row.append(merged)
        board = board.with_row(habitat, tuple(row))
    if read.counters.food is not None:
        board = replace(board, food=read.counters.food)
    if read.counters.cubes is not None:
        board = replace(board, cubes=read.counters.cubes)
    return board, tuple(problems)


@dataclass(frozen=True)
class Resume:
    """再開のとき、画面から読めないもの(手札の枚数、ラウンド、ボーナスの枚数)。手番開始のダイアログが出ていれば、ラウンドは読める。"""

    hand_size: int | None = None  # 手札の全部の枚数(ボーナスを含む)
    round_no: int | None = None  # 1〜4
    bonus_count: int = 1


TURN_START_AT = Point(1216, 650)  # 手番開始のダイアログ(中央)を押す位置(RESULT.md §11)
BOOTSTRAP_TRIES = 12
UNKNOWN_DECK_SIZE = 80  # 山札は不明。読めない札を多めに並べる(引いても、置く・払うの対象にならない)
KNOWN_BONUS_NAMES = ("野鳥調査員", "鷹匠", "飼育管理者", "草原管理者")  # 実機で見えたボーナス
_FREE_TASKS: dict[PromptKind, Task] = {
    PromptKind.PICK_DIE: GainFoodTask(1),
    PromptKind.LAY_EGGS: LayEggsTask(1),
    PromptKind.PICK_CARD: DrawTask(1),
    PromptKind.DRAW_DECK: DrawTask(1),  # 山札だけが選べる(トレイは使えない。下で空にする)
}
_BOOTSTRAP_CONFIRM_SCREENS = frozenset(
    {f"prompt:{PromptKind.POWER_GAIN.value}", f"prompt:{PromptKind.POWER_GAIN_CACHE.value}"}
)
_CONFIRM_PROMPTS = frozenset({PromptKind.POWER_GAIN, PromptKind.POWER_GAIN_CACHE})
_SKIP_PROMPTS = frozenset({PromptKind.POWER_MOVE, PromptKind.NOTHING_TO_DO, PromptKind.UNKNOWN})


def initial_tracked_state(
    me: int,
    table: CardTable,
    read: MatRead,
    hand: list[str],
    bonus_count: int,
    round_index: int,
) -> WingspanState:
    """再開のときの初期状態。自分の盤は画面から、相手の盤は空から(キューブは自分と同じ)。"""
    cubes = read.counters.cubes or 0
    mine, _ = merge_board(PlayerBoard(), read)
    mine = replace(
        mine,
        hand=tuple(hand[bonus_count:]),
        bonus=tuple(hand[:bonus_count]),
        cubes=cubes,
    )
    players = [PlayerBoard(cubes=cubes), PlayerBoard(cubes=cubes)]
    players[me] = mine
    return WingspanState(
        players=(players[0], players[1]),
        to_move=me,
        first_player=me,
        round_index=round_index,
        feeder=read.feeder,
        tray=read.tray,
        deck=(UNKNOWN_CARD,) * UNKNOWN_DECK_SIZE,
        discard=(),
        goals=(GoalTile("unknown"),) * 4,
        queue=(),
        seed=1,
    )


def _round_advanced(previous: WingspanState, cubes: int | None, me: int) -> bool:
    """キューブが、次のラウンドの手番数まで増えていれば、ラウンドが替わった。"""
    nxt = previous.round_index + 1
    if cubes is None or nxt >= len(TURNS_PER_ROUND):
        return False
    return cubes == TURNS_PER_ROUND[nxt] and cubes > previous.players[me].cubes


class WingspanRecognizer:
    def __init__(
        self,
        me: int = 0,
        table: CardTable | None = None,
        read_lines: LineReader | None = None,
        templates: dict[str, Glyph] | None = None,
        tracker: Tracker | None = None,
        resume: Resume | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._me = me
        self._table = table or default_table()
        self._read_lines = read_lines
        self._dialog_lines: LineReader | None = (
            read_lines  # 偽の OCR を渡したときは、同じものを使う
        )
        self._templates = templates
        self._tracker = tracker or Tracker()
        self._resume = resume or Resume()
        self._sleep = sleep

    @property
    def tracker(self) -> Tracker:
        return self._tracker

    def _bootstrap(self, io: GameIo) -> Recognition[WingspanState]:
        """追跡の状態が無いとき(最初の観測)に、画面から初期状態を作る。

        手番開始のダイアログが出ていれば、ラウンドを読んでから閉じる(閉じる 1 タップだけを送る)。何も重ならない盤が出たら、
        盤・餌・キューブ・餌箱・トレイを読み、手札の札名を 1 枚ずつ拡大して読む(手札の枚数と、ラウンドは、画面から読めないので、
        `Resume` で渡す)。山札は不明(読めない札のまま)、目的は読めない目的(0 点)、相手の盤は空から始める。
        """
        resume = self._resume
        for _ in range(BOOTSTRAP_TRIES):
            image = io.capture().image
            name = self.screen_name(image)
            if name == "dialog:turn_start":
                round_no, _remaining = parse_turn_header(
                    read_dialog(image, self._dialog_reader()).text
                )
                self._tracker.round_hint = round_no or self._tracker.round_hint
                io.perform(Tap(TURN_START_AT))
                self._sleep(3.0)
            elif name == "setup:keep":
                return self._setup_keep(image, None)
            elif name == "habitat":
                # 新しい対局の既定は生息地の表示。全体ボードに切り替える。ボタンは切り替え(トグル)なので、
                # 押した後は、画面が変わるまで待ち、再び押さない(切り替えの途中を「まだ生息地」と読んで 2 度押すと、元に戻る)
                io.perform(Tap(Point(*layout.MAT_BUTTON)))
                for _wait in range(8):
                    self._sleep(1.0)
                    if self.screen_name(io.capture().image) != "habitat":
                        break
            elif name == "mat":
                break
            elif name in _BOOTSTRAP_CONFIRM_SCREENS:
                # 能力の獲得の確認(決定ではない)。確定を押して閉じる。決定が要る案内(餌・卵・札の選択)は、
                # 何を選ぶ途中か分からず、手札の拡大も安全と確かめていないので、ここでは扱わない
                io.perform(Tap(Point(*layout.CONFIRM)))
                self._sleep(3.0)
            elif name == "opponent_turn":
                self._sleep(2.0)
            else:
                return _unknown(f"bootstrap:{name}", "bootstrap_screen")
        else:
            return _unknown("bootstrap", "bootstrap_timeout")
        image = io.capture().image
        if viewing(image) is not Viewing.ME:
            return _unknown("bootstrap", "bootstrap_not_my_board")
        round_no = self._tracker.round_hint or resume.round_no
        if resume.hand_size is None or round_no is None:
            return _unknown("bootstrap", "resume_required:hand_size,round")
        read = read_mat(image, self.reader(), self._table, self._templates)
        if read.problems:
            return _unknown("bootstrap", *read.problems)
        names = [*self._table.birds, *KNOWN_BONUS_NAMES]
        hand = read_hand_names(io, resume.hand_size, self.reader(), names)
        if hand is None:
            return _unknown("bootstrap", "bootstrap_hand_zoom_stuck")
        state = initial_tracked_state(
            self._me, self._table, read, hand, resume.bonus_count, round_no - 1
        )
        return Recognition(UiState(UiKind.PLAYABLE, "bootstrap"), state, 1.0)

    def reader(self) -> LineReader:
        """札名・案内を読む OCR(遅延して作る)。executor の手札読みも、同じものを使う。"""
        if self._read_lines is None:
            self._read_lines = japanese_reader()
        return self._read_lines

    def observe(self, io: GameIo, previous: WingspanState | None) -> Recognition[WingspanState]:
        """追跡の状態(executor が置いた予測)を土台に読む。無ければ、再開の初期状態を作る。"""
        tracked = self._tracker.state
        if tracked is None:
            result = self._bootstrap(io)
        else:
            result = self.recognize(io.capture().image, tracked)
        if result.state is not None:
            self._tracker.state = result.state
        return result

    def recognize(self, image: Image, previous: WingspanState | None) -> Recognition[WingspanState]:
        if previous is not None and previous.ack:
            previous = replace(previous, ack="")  # 前の確認は済んだ。画面から決め直す
        info = classify(image)
        setup = self._setup_kind(image, info.kind)
        if setup is SetupKind.KEEP:
            return self._setup_keep(image, previous)
        if setup is SetupKind.BONUS:
            return _unknown(
                "setup:bonus", "setup_bonus_standalone"
            )  # 鳥と餌の選択から通して行う(途中からは読めない)
        if info.kind is ScreenKind.DIALOG:
            return self._dialog(image, previous)
        if info.kind is ScreenKind.HABITAT and not info.prompt:
            # 生息地の表示(新しい対局の既定)。全体ボードに切り替える確認の手を出す
            if previous is None:
                return _unknown("habitat", "no_previous_state")
            state = replace(previous, to_move=self._me, ack="mat_view")
            return Recognition(UiState(UiKind.PLAYABLE, "habitat"), state, 1.0)
        if info.kind is ScreenKind.CONFIRM:
            if is_skip_confirm(image, self._dialog_reader()):
                return Recognition(UiState(UiKind.WAITING, "confirm:skip"), None, 1.0)
            return _unknown("confirm", "confirm_unknown")
        if info.kind in (ScreenKind.UNKNOWN, ScreenKind.MAT) and is_toast(image):
            # OS の通知(実績の解除など)が重なっている。数秒で消えるので、待つ
            return Recognition(UiState(UiKind.WAITING, "toast"), None, 1.0)
        if info.kind is not ScreenKind.MAT:
            return _unknown(info.kind.value, f"screen:{info.kind.value}")
        if info.prompt:
            return self._prompt(image, previous)
        owner = viewing(image)
        if owner is Viewing.UNKNOWN:
            return _unknown("mat", "viewing")
        if owner is Viewing.OPPONENT:
            return self._board(image, previous, mine=False)
        if opponent_is_playing(image) is not False:
            return Recognition(UiState(UiKind.WAITING, "opponent_turn"), None, 1.0)
        if previous is not None and previous.to_move != self._me:
            # 追跡では相手の手番。砂時計が出る前(確定の約 1.2 秒後まで)の盤だけの画面は、自分の手番ではない。
            # 手番開始のダイアログが出るまで待つ
            return Recognition(UiState(UiKind.WAITING, "opponent_turn"), None, 1.0)
        return self._board(image, previous, mine=True)

    def _setup_kind(self, image: Image, kind: ScreenKind) -> SetupKind:
        """初期選択の画面か。色の判別が不明・ダイアログの画面だけ、題を OCR で確かめる(盤の画面では読まない)。"""
        # 初期選択の画面は、色の判別では 不明・ダイアログ・生息地の表示(ボーナスの選択)のどれにもなりうる
        if kind in (ScreenKind.UNKNOWN, ScreenKind.DIALOG, ScreenKind.HABITAT):
            return read_setup(image, self._dialog_reader())
        return SetupKind.NONE

    def _setup_keep(
        self, image: Image, previous: WingspanState | None
    ) -> Recognition[WingspanState]:
        """初期選択の「鳥と餌を 5 つ」の画面。追跡の決定(SetupTask)が残っていればそれ、無ければ鳥 5 枚の札名を読んで初期状態を作る。"""
        screen = "setup:keep"
        if previous is not None and previous.queue and isinstance(previous.queue[0], SetupTask):
            return Recognition(UiState(UiKind.PLAYABLE, screen), previous, 1.0)
        reader = self._dialog_reader()
        hand: list[str] = []
        for index in range(len(layout.SETUP_CARD_X)):
            text = "".join(reader(image, layout.setup_name_rect(index)))
            found = match_name(text, self._table.birds)
            hand.append(found.name if found else UNKNOWN_CARD)
        mine = PlayerBoard(
            hand=tuple(hand),
            bonus=(UNKNOWN_CARD, UNKNOWN_CARD),  # ボーナスは次の画面。名前は読まず、左の札を選ぶ
            food=(1, 1, 1, 1, 1),
            cubes=_TURNS[0],
        )
        players = [PlayerBoard(cubes=_TURNS[0]), PlayerBoard(cubes=_TURNS[0])]
        players[self._me] = mine
        state = WingspanState(
            players=(players[0], players[1]),
            to_move=self._me,
            first_player=self._me,
            round_index=0,
            feeder=(),
            tray=(UNKNOWN_CARD,) * 3,
            deck=(UNKNOWN_CARD,) * UNKNOWN_DECK_SIZE,
            discard=(),
            goals=(GoalTile("unknown"),) * 4,
            queue=(SetupTask(),),
            pending_setup=(self._me,),
            seed=1,
        )
        return Recognition(UiState(UiKind.PLAYABLE, screen), state, 1.0)

    def screen_name(self, image: Image) -> str:
        """盤を読まずに、画面の名前だけを返す(executor が操作の後に画面の変化を待つときの、軽い判別)。

        prompt:<種類> / dialog:<種類> / opponent_turn / mat(何も重ならない盤。自分か相手の盤かは区別しない) / habitat / unknown
        """
        info = classify(image)
        setup = self._setup_kind(image, info.kind)
        if setup is not SetupKind.NONE:
            return f"setup:{setup.value}"
        if info.kind is ScreenKind.DIALOG:
            return f"dialog:{read_dialog(image, self._dialog_reader()).kind.value}"
        if info.kind is ScreenKind.MAT:
            if info.prompt:
                return f"prompt:{read_prompt(image, self.reader()).kind.value}"
            return "opponent_turn" if opponent_is_playing(image) is True else "mat"
        if info.kind is ScreenKind.HABITAT:
            return "habitat_prompt" if info.prompt else "habitat"
        if info.kind is ScreenKind.CONFIRM:
            return "confirm:skip" if is_skip_confirm(image, self._dialog_reader()) else "unknown"
        return "unknown"

    def _dialog(self, image: Image, previous: WingspanState | None) -> Recognition[WingspanState]:
        """中央のダイアログ。押してはいけないもの(ストア、ゲームのメニュー)は FORBIDDEN、終局の画面は GAME_OVER。

        手番の開始とラウンドの採点は、閉じる操作が要る(確認を求める画面)ので、`ack` を立てた状態で PLAYABLE にする。
        """
        read = read_dialog(image, self._dialog_reader())
        screen = f"dialog:{read.kind.value}"
        if read.kind in (DialogKind.STORE, DialogKind.GAME_MENU):
            return Recognition(UiState(UiKind.FORBIDDEN, screen), None, 1.0)
        if read.kind in (DialogKind.FINAL, DialogKind.SAVE_PROMPT):
            return Recognition(UiState(UiKind.GAME_OVER, screen), None, 1.0)
        if read.kind is DialogKind.UNKNOWN:
            if previous is not None and previous.terminal:
                # 最後のラウンドの採点の確認の直後は、得点の演出の始まりで、文言が決まらない一瞬がある。終局として扱う
                return Recognition(UiState(UiKind.GAME_OVER, "dialog:final"), None, 1.0)
            return _unknown(screen, "dialog_unknown")
        if previous is None:
            return _unknown(screen, "no_previous_state")
        if read.kind is DialogKind.TURN_START:
            return Recognition(UiState(UiKind.PLAYABLE, screen), self._turn_started(previous), 1.0)
        if read.kind is DialogKind.ROUND_SCORE:
            return Recognition(UiState(UiKind.PLAYABLE, screen), self._round_scored(previous), 1.0)
        return _unknown(screen, "dialog_unhandled")

    def _turn_started(self, previous: WingspanState) -> WingspanState:
        """手番開始のダイアログ。相手が手番を終えて、自分の番になった(相手のキューブを 1 つ減らす)。"""
        state = previous
        if previous.to_move != self._me and previous.players[previous.to_move].cubes > 0:
            opp = previous.to_move
            board = previous.players[opp]
            state = previous.with_player(opp, replace(board, cubes=board.cubes - 1))
        return replace(state, to_move=self._me, ack="turn_start", queue=())

    def _round_scored(self, previous: WingspanState) -> WingspanState:
        """ラウンドの採点の画面。追跡がまだ前のラウンドなら、ラウンドを終える(目的の点は、読めない目的として 0 点)。"""
        fresh = all(
            b.cubes == TURNS_PER_ROUND[min(previous.round_index, 3)] for b in previous.players
        )
        state = previous if fresh or previous.terminal else end_round(previous, self._table)
        return replace(state, ack="round", queue=())

    def _dialog_reader(self) -> LineReader:
        if self._dialog_lines is None:
            self._dialog_lines = japanese_reader(scale=DIALOG_SCALE)
        return self._dialog_lines

    def _prompt(self, image: Image, previous: WingspanState | None) -> Recognition[WingspanState]:
        """案内パネルが出ている盤。追跡している決定と合う案内なら、その決定(PLAYABLE)。

        決定ではない案内(実装済みの無料の獲得などの確認、未実装の能力)は、確認を受ける / スキップする手にする。
        どちらでもなければ止める(推測で押さない)。
        """
        read = read_prompt(image, self.reader())
        screen = f"prompt:{read.kind.value}"
        if previous is None:
            return _unknown(screen, "no_previous_state")
        task = previous.queue[0] if previous.queue else None
        if task is not None and read.kind in expected_prompts(task):
            return Recognition(UiState(UiKind.PLAYABLE, screen), previous, 1.0)
        free = _FREE_TASKS.get(read.kind)
        if free is not None and read.kind is PromptKind.LAY_EGGS:
            # 置ける鳥が無いのに「産卵してください」が残る(実機: 鳥が満卵で余りが出た)。決定ではなく、確定を押して閉じる
            me = replace(previous, to_move=self._me)
            if not eggable(me, self._table, self._me):
                free = None
                read = replace(read, kind=PromptKind.POWER_GAIN)  # 確認(確定)を受ける案内として扱う
        if free is not None:
            # 追跡している決定が無いのに出た「餌を選ぶ / 卵を置く / 札を選ぶ」の案内。相手の鳥の能力(全員が得る)で、
            # 自分にも 1 回ぶんの選択が回ってきた(実機: ノドアカハチドリ)。1 回ぶんの決定として扱う
            state = replace(previous, to_move=self._me, queue=(free,))
            if read.kind is PromptKind.PICK_DIE:
                state = replace(state, feeder=feeder_faces(image))  # 餌箱のダイスは盤の上に見える
            elif read.kind is PromptKind.DRAW_DECK:
                state = replace(state, tray=("", "", ""))  # 山札から引く。トレイの札は選べない
            elif read.kind is PromptKind.PICK_CARD:
                state = replace(
                    state, tray=draw_screen_tray(image)
                )  # 選べる札だけが明るい。追跡の古い値を使わない
            return Recognition(UiState(UiKind.PLAYABLE, screen), state, 1.0)
        if read.kind in _CONFIRM_PROMPTS:
            ack = "confirm"
        elif read.kind in _SKIP_PROMPTS:
            ack = "skip"
        else:
            return _unknown(screen, f"prompt_mismatch:{read.kind.value}")
        state = replace(previous, to_move=self._me, ack=ack, queue=())
        return Recognition(UiState(UiKind.PLAYABLE, screen), state, 1.0)

    def _board(
        self, image: Image, previous: WingspanState | None, *, mine: bool
    ) -> Recognition[WingspanState]:
        screen = "my_turn" if mine else "opponent_board"
        if previous is None:
            return _unknown(screen, "no_previous_state")
        read = read_mat(image, self.reader(), self._table, self._templates)
        index = self._me if mine else 1 - self._me
        board, problems = merge_board(previous.players[index], read)
        problems = (*read.problems, *problems)
        state = previous.with_player(index, board)
        if mine:
            if previous.queue:
                problems = (*problems, "decision_pending")
            if _round_advanced(previous, read.counters.cubes, self._me):
                state = replace(
                    state,
                    round_index=previous.round_index + 1,
                    first_player=(previous.first_player + 1) % len(previous.players),
                )
            state = replace(state, feeder=read.feeder, tray=read.tray, to_move=self._me)
        if problems:
            return Recognition(UiState(UiKind.UNKNOWN, screen), None, LOW_CONFIDENCE, problems)
        kind = UiKind.PLAYABLE if mine else UiKind.WAITING
        return Recognition(UiState(kind, screen), state, 1.0)

    def debug_overlay(self, frame: Frame, result: Recognition[WingspanState]) -> NDArray[np.uint8]:
        out = np.asarray(frame.image).copy()
        text = f"{result.ui.kind.value}:{result.ui.screen} conf={result.confidence:.2f}"
        cv2.putText(out, text, (40, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 255, 255), 3)
        for i, problem in enumerate(result.low_confidence[:6]):
            cv2.putText(
                out, problem, (40, 110 + 40 * i), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2
            )
        return out
