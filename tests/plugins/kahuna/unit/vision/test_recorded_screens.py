"""録画した画面(Git管理外)での認識と操作のテスト。評価セットが無い環境では飛ばす。"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest
from tests.plugins.kahuna.support.helpers import make_state

from bglm.core.models import Frame, InputAction, Point, Tap, UiKind
from bglm.plugins.kahuna.logic.models import (
    DrawDeck,
    DrawMarket,
    KahunaState,
    PlaceStick,
    Player,
    default_board,
)
from bglm.plugins.kahuna.vision.describe import describe_recognition
from bglm.plugins.kahuna.vision.executor import KahunaExecutor
from bglm.plugins.kahuna.vision.recognizer import CONTINUE_BUTTON, KahunaRecognizer
from bglm.plugins.kahuna.vision.screens import LOADING, classify_screen
from bglm.plugins.kahuna.vision.templates import DEFAULT_DIR, TemplateSet

EVAL = Path("datasets/eval/kahuna")
pytestmark = pytest.mark.skipif(
    not (EVAL / "session1_000.json").exists() or not DEFAULT_DIR.exists(),
    reason="評価セットまたはテンプレート(Git管理外)が無い",
)

BOARD = default_board()


@pytest.fixture(scope="module")
def templates() -> TemplateSet:
    return TemplateSet.load()


@pytest.fixture(scope="module")
def labels() -> dict[str, Any]:
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(EVAL.glob("*.json"))}


def _image(name: str) -> np.ndarray:
    path = EVAL / f"{name}.png"
    return np.asarray(cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR))


def _state() -> KahunaState:
    return make_state()


def test_every_recorded_screen_is_classified_as_labelled(
    templates: TemplateSet, labels: dict[str, Any]
) -> None:
    got = {name: classify_screen(_image(name), templates).name for name in labels}
    wrong = {n: g for n, g in got.items() if g != labels[n]["screen"]}
    assert wrong == {}


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("session1_000", UiKind.UNKNOWN),  # ステージ選択: 対戦の開始は人が行う
        ("session1_024", UiKind.UNKNOWN),  # ゲームオプション
        ("session1_026", UiKind.UNKNOWN),  # 再開の確認
        ("session1_027", UiKind.WAITING),  # 読み込み中
        ("session1_009", UiKind.WAITING),  # 「READY FOR A NEW ROUND」の帯
        ("session1_021", UiKind.UNKNOWN),  # チュートリアルの案内
        ("session1_033", UiKind.WAITING),  # 相手の手番(手札が暗い)
        ("session1_063", UiKind.WAITING),  # 決算(CONTINUE)
        ("session1_018", UiKind.PLAYABLE),
        ("session1_170", UiKind.GAME_OVER),
    ],
)
def test_screen_kinds(templates: TemplateSet, name: str, kind: UiKind) -> None:
    assert classify_screen(_image(name), templates).kind is kind


def test_wrong_size_and_uniform_images(templates: TemplateSet) -> None:
    assert classify_screen(np.zeros((100, 100, 3), np.uint8), templates).kind is UiKind.UNKNOWN
    uniform = np.full((1080, 2432, 3), (102, 45, 4), np.uint8)
    assert classify_screen(uniform, templates).name == LOADING


def test_verified_frames_match_their_element_labels(labels: dict[str, Any]) -> None:
    recognizer = KahunaRecognizer()
    checked = 0
    for name, label in labels.items():
        if "elements" not in label:
            continue
        assert describe_recognition(recognizer.recognize(_image(name))) == label["elements"], name
        checked += 1
    assert checked >= 5


def test_game_end_reads_my_win(templates: TemplateSet) -> None:
    recognition = KahunaRecognizer(templates).recognize(_image("session1_170"))
    assert recognition.ui.kind is UiKind.GAME_OVER
    assert recognition.state is not None
    assert recognition.state.over and recognition.state.winner is Player.ME


class _ReplayIo:
    """決まった画像を順に返し(最後の画像は繰り返す)、入力を記録する。"""

    def __init__(self, *images: np.ndarray) -> None:
        self._images = list(images)
        self.actions: list[InputAction] = []

    def capture(self) -> Frame:
        image = self._images.pop(0) if len(self._images) > 1 else self._images[0]
        return Frame.from_image(image, datetime.now())

    def perform(self, action: InputAction) -> None:
        self.actions.append(action)


def test_round_end_dialog_is_advanced_with_one_tap(templates: TemplateSet) -> None:
    io = _ReplayIo(_image("session1_063"))
    recognition = KahunaRecognizer(templates).observe(io, None)
    assert recognition.ui.kind is UiKind.WAITING
    assert io.actions == [Tap(CONTINUE_BUTTON)]


def test_game_end_dialog_sends_no_input(templates: TemplateSet) -> None:
    io = _ReplayIo(_image("session1_170"))
    KahunaRecognizer(templates).observe(io, None)
    assert io.actions == []


def test_unreadable_my_turn_is_retried_then_returned(templates: TemplateSet) -> None:
    sleeps: list[float] = []
    recognizer = KahunaRecognizer(templates, sleep=sleeps.append)
    recognition = recognizer.observe(_ReplayIo(_image("session1_034")), None)  # カードの動き
    assert recognition.state is None and "market" in recognition.low_confidence
    assert len(sleeps) == 2


def _executor(templates: TemplateSet) -> KahunaExecutor:
    return KahunaExecutor(templates, sleep=lambda _s: None)


def _my_stick_line(templates: TemplateSet, name: str) -> int:
    state = KahunaRecognizer(templates).recognize(_image(name)).state
    assert state is not None
    return next(i for i, owner in enumerate(state.sticks) if owner is Player.ME)


def test_place_stick_taps_card_then_line_and_confirms(templates: TemplateSet) -> None:
    line = _my_stick_line(templates, "session1_072")
    io = _ReplayIo(_image("session1_072"), _image("session1_072"))
    card = BOARD.island_index("LALE")
    result = _executor(templates).execute(io, _state(), PlaceStick(card, line))
    assert result.success, result.reason
    assert len(io.actions) == 2
    assert io.actions[1] == Tap(BOARD.lines[line].position)


def test_place_stick_fails_when_no_stick_appears(templates: TemplateSet) -> None:
    recognizer = KahunaRecognizer(templates)
    mine = recognizer.recognize(_image("session1_072")).state
    empty = recognizer.recognize(_image("session1_018")).state
    assert mine is not None and empty is not None
    line = next(  # 018 では空いている、072 では自分の杖コマがある点線
        i for i, o in enumerate(mine.sticks) if o is Player.ME and empty.sticks[i] is None
    )
    io = _ReplayIo(_image("session1_072"), _image("session1_018"))
    card = BOARD.island_index("LALE")
    result = _executor(templates).execute(io, _state(), PlaceStick(card, line))
    assert not result.success
    assert len(io.actions) == 2  # 押した後に確認して失敗


def test_place_stick_refuses_when_card_not_in_hand(templates: TemplateSet) -> None:
    io = _ReplayIo(_image("session1_018"))
    result = _executor(templates).execute(io, _state(), PlaceStick(BOARD.island_index("ALOA"), 0))
    assert not result.success and io.actions == []


def test_place_stick_refuses_on_opponent_turn(templates: TemplateSet) -> None:
    io = _ReplayIo(_image("session1_033"))
    result = _executor(templates).execute(io, _state(), PlaceStick(0, 0))
    assert not result.success and io.actions == []


def test_draw_market_taps_the_slot(templates: TemplateSet) -> None:
    io = _ReplayIo(_image("session1_018"), _image("session1_033"))  # 引いた後は手札が暗い
    result = _executor(templates).execute(io, _state(), DrawMarket(BOARD.island_index("JOJO")))
    assert result.success, result.reason
    assert len(io.actions) == 1
    tap = io.actions[0]
    assert isinstance(tap, Tap) and tap.at.x > 1600  # 3枚目の枠


def test_deck_draw_reports_unconfirmed_when_hand_does_not_grow(templates: TemplateSet) -> None:
    # 同じ画像が返るので、手札は増えない。引けたと判断せず失敗を返す
    io = _ReplayIo(_image("session1_018"))
    result = _executor(templates).execute(io, _state(), DrawDeck())
    assert not result.success
    assert "確認できない" in (result.reason or "")
    assert len(io.actions) == 1


SHIFT = 72  # 実機で見た表示のずれ(画素。画面は左へ動いていた)


def _shifted(name: str) -> np.ndarray:
    """録画を左へ SHIFT 画素ずらした画像。実機の表示と同じ向きのずれ。"""
    image = _image(name)
    moved = np.zeros_like(image)
    moved[:, :-SHIFT] = image[:, SHIFT:]
    return moved


def test_shifted_display_is_read_the_same_as_the_recording(templates: TemplateSet) -> None:
    recognizer = KahunaRecognizer(templates)
    recorded = recognizer.recognize(_image("session1_018"))
    shifted = recognizer.recognize(_shifted("session1_018"))
    assert shifted.ui.screen == recorded.ui.screen == "my_turn"
    assert describe_recognition(shifted) == describe_recognition(recorded)


def test_unalignable_image_is_unknown_and_sends_nothing(templates: TemplateSet) -> None:
    noise = np.random.default_rng(1).integers(0, 255, (1080, 2432, 3), dtype=np.uint8)
    io = _ReplayIo(noise)
    recognition = KahunaRecognizer(templates).observe(io, None)
    assert recognition.ui.kind is UiKind.UNKNOWN and recognition.state is None
    assert io.actions == []


def test_place_stick_taps_are_moved_to_the_shifted_display(templates: TemplateSet) -> None:
    recognizer = KahunaRecognizer(templates)
    mine = recognizer.recognize(_image("session1_072")).state
    empty = recognizer.recognize(_image("session1_018")).state
    assert mine is not None and empty is not None
    line = next(i for i, o in enumerate(mine.sticks) if o is Player.ME and empty.sticks[i] is None)
    io = _ReplayIo(_shifted("session1_072"), _shifted("session1_072"))
    card = BOARD.island_index("LALE")
    result = _executor(templates).execute(io, _state(), PlaceStick(card, line))
    assert result.success, result.reason
    target = BOARD.lines[line].position
    assert io.actions[1] == Tap(Point(target.x - SHIFT, target.y))


def test_title_screen_is_named_without_alignment(templates: TemplateSet) -> None:
    """タイトルには基準(FISHERMAN の名前)が無いが、位置を使わないので画面名は読める。"""
    recognition = KahunaRecognizer(templates).recognize(_image("session1_000"))
    assert recognition.ui.screen == "menu"
    assert recognition.state is None


def test_new_actions_refuse_on_opponent_turn(templates: TemplateSet) -> None:
    from bglm.plugins.kahuna.logic.models import DiscardCard, DrawDeck, PassDraw, RemoveStick

    io = _ReplayIo(_image("session1_033"))  # 相手の手番
    executor = _executor(templates)
    held = make_state(hand=("ALOA",))  # 手札が残っていると、相手の手番では操作しない
    assert not executor.execute(io, held, DrawDeck()).success
    assert not executor.execute(io, held, PassDraw()).success
    assert not executor.execute(io, held, DiscardCard(0)).success
    assert not executor.execute(io, held, RemoveStick((0, 1), 0)).success
    assert io.actions == []


def test_discard_refuses_when_card_not_in_hand(templates: TemplateSet) -> None:
    from bglm.plugins.kahuna.logic.models import DiscardCard

    io = _ReplayIo(_image("session1_018"))  # 手札は ALOA、BARI、LALE
    result = _executor(templates).execute(io, _state(), DiscardCard(BOARD.island_index("KAHU")))
    assert not result.success and io.actions == []


def test_remove_refuses_when_a_card_is_missing(templates: TemplateSet) -> None:
    from bglm.plugins.kahuna.logic.models import RemoveStick

    io = _ReplayIo(_image("session1_018"))
    result = _executor(templates).execute(
        io, _state(), RemoveStick((BOARD.island_index("KAHU"), BOARD.island_index("LALE")), 26)
    )
    assert not result.success and io.actions == []
