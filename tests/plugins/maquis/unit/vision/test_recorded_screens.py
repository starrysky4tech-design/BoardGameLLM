"""記録した実画面での読み取りの確認。画面の素材は Git 管理外なので、無ければ飛ばす。

期待値は、実機で対局しながら記録した観測(ログの出現地点、画面の写真、資材の丸)から手で作った。
コードの出力から作っていない。どの画面も、1枚の画像だけから読む。
"""

import pytest
from tests.plugins.maquis.support.helpers import frame_path, load_frame_image

from bglm.plugins.maquis.logic.board import default_board
from bglm.plugins.maquis.logic.models import Phase
from bglm.plugins.maquis.vision import cards, layout
from bglm.plugins.maquis.vision.board_reading import read_board
from bglm.plugins.maquis.vision.screens import ScreenKind, classify_screen

BOARD = default_board()
FENCE = "black_market_fence"


def skip_without(*names: str) -> None:
    missing = [n for n in names if not frame_path(n).exists()]
    if missing:
        pytest.skip(f"記録画面が無い(Git管理外): {missing}")


# (画面, フェイズ, 未配置, 使える団員, 団員のいる枠, 巡回の地点, 監獄, ★(A, B), 士気, 薬品)
BOARDS = [
    # 4局目 ターン1(対局の開始直後 → 3人を配置 → 行動)。ログ: 無線A・無線B・故買屋に巡回が出現
    ("game_001", Phase.PLACEMENT, 3, 3, (), set(), False, (0, 0), 6, 0),
    ("y_p1", Phase.PLACEMENT, 2, 3, ("grocer",), {"radio_a"}, False, (0, 0), 6, 0),
    (
        "y_p2",
        Phase.PLACEMENT,
        1,
        3,
        ("doctor", "grocer"),
        {"radio_a", "radio_b"},
        False,
        (0, 0),
        6,
        0,
    ),
    (
        "y_p3",
        Phase.PLACEMENT,
        0,
        3,
        ("cafe", "doctor", "grocer"),
        {"radio_a", "radio_b", FENCE},
        False,
        (0, 0),
        6,
        0,
    ),
    # 全員が帰還した後(行動フェイズ)。カフェで勧誘して 4人、医者で薬品1
    ("y_a4", Phase.ACTION, 0, 4, (), {"radio_a", "radio_b", FENCE}, False, (0, 0), 6, 1),
    ("y_end", Phase.PLACEMENT, 4, 4, (), set(), False, (0, 0), 6, 1),
    # 4局目 ターン2: 4人配置(カフェ・畑・畑・任務B)。巡回は食料品店・ポン・レヴェック・無線A・ポン・デュ・ノール
    (
        "z_p4b",
        Phase.PLACEMENT,
        0,
        4,
        ("cafe", "field_e", "field_w", "mission_b"),
        {"grocer", "pont_leveque", "radio_a", "pont_du_nord"},
        False,
        (0, 0),
        6,
        1,
    ),
    # 任務Bの行動で★が1つ点灯(団員は帰還できず残る)
    (
        "z_a2",
        Phase.ACTION,
        0,
        4,
        ("cafe", "field_e", "field_w", "mission_b"),
        {"grocer", "pont_leveque", "radio_a", "pont_du_nord"},
        False,
        (0, 1),
        6,
        1,
    ),
    # ターン3(監獄に1人、士気 5)。行動で2つ目の★が点灯し、任務Bの団員は帰還した
    (
        "v_a2",
        Phase.ACTION,
        0,
        3,
        ("cafe", "field_e"),
        {FENCE, "radio_b", "grocer"},
        True,
        (0, 2),
        5,
        1,
    ),
]


@pytest.mark.parametrize(
    (
        "name",
        "phase",
        "unplaced",
        "total",
        "agents",
        "patrols",
        "prison",
        "stars",
        "morale",
        "medicine",
    ),
    BOARDS,
)
def test_board_is_read_as_observed(
    name: str,
    phase: Phase,
    unplaced: int,
    total: int,
    agents: tuple[str, ...],
    patrols: set[str],
    prison: bool,
    stars: tuple[int, int],
    morale: int,
    medicine: int,
) -> None:
    skip_without(name)
    result = read_board(load_frame_image(name), BOARD)
    assert result.problems == ()
    reading = result.reading
    assert reading is not None
    assert reading.phase is phase
    assert (reading.unplaced, reading.agents_total) == (unplaced, total)
    assert reading.agents == tuple(sorted(agents))
    assert reading.patrols == patrols
    assert reading.prison is prison
    assert reading.stars == stars
    assert reading.resources.morale == morale
    assert reading.resources.medicine == medicine
    assert reading.confidence >= 0.8


def test_an_unknown_mission_stops_the_reading() -> None:
    # 3局目の任務Bは「暗殺」。★の位置と箱が未確認なので、読まずに止まる
    skip_without("s_p3")
    result = read_board(load_frame_image("s_p3"), BOARD)
    assert result.reading is None
    assert result.fatal
    assert result.problems == ("mission_unknown:mission_b",)


SCREENS = [
    ("game_001", ScreenKind.BOARD),
    ("v_a2", ScreenKind.BOARD),
    ("r_t3", ScreenKind.CONFIRM),  # 「ターンを終了しますか?」
    ("x_t1_end2", ScreenKind.END_DEFEAT),  # 「レジスタンス壊滅」
    ("m_menu", ScreenKind.TITLE),
    ("g_deck_05", ScreenKind.DECK),
    ("q_deck", ScreenKind.DECK),
    ("rules_01", ScreenKind.UNKNOWN),
    ("settings", ScreenKind.UNKNOWN),
    ("info", ScreenKind.UNKNOWN),
    ("stats", ScreenKind.UNKNOWN),
    ("newgame_01", ScreenKind.UNKNOWN),
    ("m_pause", ScreenKind.UNKNOWN),
]


@pytest.mark.parametrize(("name", "expected"), SCREENS)
def test_screen_kind(name: str, expected: ScreenKind) -> None:
    skip_without(name)
    assert classify_screen(load_frame_image(name)) is expected


def test_discard_top_card_is_read_from_the_deck_screen() -> None:
    # 3局目 ターン1の最後に引かれた巡回カード(捨札の先頭)は、①食料品店 ②貧民街 ③医者
    skip_without("q_deck")
    card, confidence, present = cards.read_discard_top(load_frame_image("q_deck"))
    assert present
    assert card == ("grocer", "slums", "doctor")
    assert confidence >= 0.9


def test_deck_first_card_is_read_from_the_deck_screen() -> None:
    # 同じ画面の山札の先頭は、①無線B ②食料品店 ③闇市
    skip_without("q_deck")
    image = load_frame_image("q_deck")
    left = cards.find_left(image, layout.DECK_FIRST_LEFT)
    assert left is not None
    assert cards.read_card(image, left)[0] == ("radio_b", "grocer", "black_market")


def test_empty_discard_is_reported_as_empty() -> None:
    skip_without("g_deck_00")
    card, _, present = cards.read_discard_top(load_frame_image("g_deck_00"))
    assert card is None
    assert not present
