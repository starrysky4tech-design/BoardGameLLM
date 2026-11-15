"""Log の出来事から位置を追う(logic/log_replay.py)のテスト。

入力は、2026-11-05 の実機の Log(自分の 9 → Vermont から、Dog の手番、自分の 6 と 5 まで)。
期待値は、画面で確認した位置から手で書く。
"""

from bglm.plugins.monopoly.logic import events as ev
from bglm.plugins.monopoly.logic.log_replay import replay_log
from bglm.plugins.monopoly.logic.models import Player

SELF, AI = Player.SELF, Player.AI


def rolled(p: Player, n: int, doubles: bool = False) -> ev.DiceRolled:
    return ev.DiceRolled(p, n, doubles)


def landed(p: Player, name: str) -> ev.LandedOn:
    return ev.LandedOn(p, name)


def test_dogs_doubles_chain_is_followed() -> None:
    # Dog は Electric Company(12)。4 のダブルで St. James(16)。続けて 4 で Free Parking(20)→ 10 で刑務所
    events: list[ev.LogEvent] = [
        ev.TurnStarted(AI),
        rolled(AI, 4, doubles=True),
        landed(AI, "St. James Place"),
        rolled(AI, 4),
        landed(AI, "Free Parking"),
    ]
    result = replay_log({SELF: 8, AI: 12}, events)
    assert result.stopped is None
    assert result.positions[AI] == 20
    assert result.corrections == []


def test_my_double_roll_is_followed_even_when_my_own_count_missed_it() -> None:
    # 実際に起きた場面: 自分は Vermont(8)。Log は rolled 6(Virginia)、rolled 5(New York)の 2 回
    events: list[ev.LogEvent] = [
        ev.TurnStarted(SELF),
        rolled(SELF, 6),
        landed(SELF, "Virginia Avenue"),
        ev.TurnStarted(AI),
        rolled(AI, 10),
        ev.SentToJail(AI),
        ev.TurnStarted(SELF),
        rolled(SELF, 5),
        landed(SELF, "New York Avenue"),
    ]
    result = replay_log({SELF: 8, AI: 20}, events)
    assert result.stopped is None
    assert result.positions[SELF] == 19  # 8 → 14 → 19(画面の New York Avenue)
    assert result.positions[AI] == 10  # 刑務所
    assert result.corrections == []


def test_mismatch_with_the_log_is_corrected_and_recorded() -> None:
    # 出目の取りこぼしの例: 自分は 8。Log の rolled 5 は 13 のはずだが、止まったのは New York(19)
    events: list[ev.LogEvent] = [rolled(SELF, 5), landed(SELF, "New York Avenue")]
    result = replay_log({SELF: 8, AI: 0}, events)
    assert result.positions[SELF] == 19
    assert len(result.corrections) == 1 and "States Avenue" in result.corrections[0]


def test_card_square_names_with_several_positions_prefer_the_computed_one() -> None:
    # Chance は盤に 3 か所(7、22、36)。計算が 22 なら、22 を採る
    result = replay_log({SELF: 15, AI: 0}, [rolled(SELF, 7), landed(SELF, "Chance")])
    assert result.positions[SELF] == 22 and result.corrections == []


def test_go_pass_wraps_around() -> None:
    result = replay_log({SELF: 39, AI: 0}, [rolled(SELF, 9), landed(SELF, "Vermont Avenue")])
    assert result.positions[SELF] == 8 and result.corrections == []


def test_landing_for_the_other_player_stops_the_replay() -> None:
    result = replay_log({SELF: 8, AI: 12}, [rolled(SELF, 5), landed(AI, "States Avenue")])
    assert result.stopped is not None


def test_unknown_lines_are_counted_and_skipped() -> None:
    result = replay_log(
        {SELF: 8, AI: 0}, [ev.UnknownLine("???"), rolled(SELF, 5), landed(SELF, "States Avenue")]
    )
    assert result.unknown_lines == 1 and result.positions[SELF] == 13


def test_roll_inside_jail_without_doubles_does_not_move() -> None:
    # 実機: Dog は 10 で刑務所へ。次の手番の rolled 4 は、刑務所の中で、動かない
    events: list[ev.LogEvent] = [
        rolled(AI, 10),
        ev.SentToJail(AI),
        ev.TurnStarted(AI),
        rolled(AI, 4),
    ]
    result = replay_log({SELF: 8, AI: 20}, events)
    assert result.positions[AI] == 10
    assert AI in result.in_jail


def test_doubles_inside_jail_release_and_move_by_the_roll() -> None:
    # 刑務所(10)の中でダブルの 6。出られて、10 + 6 = 16(St. James Place)に止まる
    result = replay_log(
        {SELF: 8, AI: 10},
        [rolled(AI, 6, doubles=True), landed(AI, "St. James Place")],
        in_jail=frozenset({AI}),
    )
    assert result.positions[AI] == 16
    assert AI not in result.in_jail
    assert result.corrections == []


def test_landed_without_a_roll_line_stops_instead_of_guessing() -> None:
    # 実機: 自分の rolled 5 の行が読めず(UnknownLine)、Marvin Gardens に止まった行だけが出た。
    # 自分は 24。出目が分からないので、位置を推測で進めず、止める
    result = replay_log(
        {SELF: 24, AI: 10}, [ev.UnknownLine("TopHatrolled5"), landed(SELF, "Marvin Gardens")]
    )
    assert result.stopped is not None and "出目の行が無い" in result.stopped
    assert result.positions[SELF] == 24


def test_landed_without_a_roll_line_is_fine_when_it_matches_the_current_square() -> None:
    # カード後などで、同じマスの「landed on」だけが出る場合は、位置と合うので止めない
    result = replay_log({SELF: 29, AI: 10}, [landed(SELF, "Marvin Gardens")])
    assert result.stopped is None


def test_third_failed_turn_in_jail_pays_bail_and_moves_by_the_roll() -> None:
    # 実機の Log: Dog は 4、6 と刑務所の中で出られず、3 回目の 8 で罰金を払って出る。
    # 10 + 8 = 18(Tennessee Avenue)。自分が家賃 ₼28 を受け取った(landed on の行は出ない)
    events: list[ev.LogEvent] = [
        rolled(AI, 4),
        rolled(AI, 6),
        rolled(AI, 8),
        ev.BailPosted(AI),
        ev.RentPaid(AI, 28, SELF),
    ]
    result = replay_log({SELF: 29, AI: 10}, events, in_jail=frozenset({AI}))
    assert result.positions[AI] == 18
    assert AI not in result.in_jail
    assert result.stopped is None


def test_bail_without_a_failed_roll_just_releases() -> None:
    result = replay_log({SELF: 29, AI: 10}, [ev.BailPosted(AI)], in_jail=frozenset({AI}))
    assert result.positions[AI] == 10 and AI not in result.in_jail


def test_position_tracker_carries_state_across_turns() -> None:
    from bglm.plugins.monopoly.logic.log_replay import PositionTracker

    tracker = PositionTracker({SELF: 29, AI: 10}, in_jail=frozenset({AI}))
    # 1 手番目: Dog は刑務所の中で 6(動けない)。自分は 5 で North Carolina... ではなく Marvin から 3 で 32
    first = tracker.advance([rolled(AI, 6), rolled(SELF, 3), landed(SELF, "North Carolina Avenue")])
    assert first.positions[AI] == 10 and first.positions[SELF] == 32
    # 2 手番目: Dog の 8 で保釈(刑務所の中の出目)。前の手番の状態を引き継ぐ
    second = tracker.advance([rolled(AI, 8), ev.BailPosted(AI), ev.RentPaid(AI, 28, SELF)])
    assert second.positions[AI] == 18 and AI not in tracker.in_jail
    # 3 手番目: Dog は 11 で 29 へ。自分は 8 で 40 → GO
    third = tracker.advance(
        [rolled(AI, 11), ev.RentPaid(AI, 48, SELF), rolled(SELF, 8), landed(SELF, "GO")]
    )
    assert third.positions[AI] == 29 and third.positions[SELF] == 0
    assert third.corrections == [] and third.stopped is None


def test_last_landed_positions_uses_the_latest_unique_square() -> None:
    from bglm.plugins.monopoly.logic.log_replay import last_landed_positions

    events: list[ev.LogEvent] = [
        ev.LandedOn(AI, "Baltic Avenue"),
        ev.LandedOn(SELF, "Jail"),
        ev.LandedOn(AI, "St. Charles Place"),
        ev.LandedOn(AI, "Chance"),  # 複数ある場所は、位置が決まらない
    ]
    out = last_landed_positions(events)
    assert out[AI] == 11


def test_direct_purchase_moves_the_buyer_to_the_square_and_counts_a_go_pass() -> None:
    # 実機: Thimble が Chance(7)に止まり、カードで Reading Railroad(5)へ進んで購入した。移動の行は Log に出ない
    events: list[ev.LogEvent] = [
        ev.DiceRolled(AI, 7, doubles=False),
        ev.AuctionWon(AI, "Reading Railroad", 200, direct=True),
    ]
    result = replay_log({SELF: 7, AI: 0}, events)
    assert result.positions[AI] == 5 and result.go_passes[AI] == 1 and len(result.corrections) == 1


def test_landed_without_a_roll_line_after_a_card_moves_to_the_square() -> None:
    # 実機: Community Chest(2)のカードで GO へ進んだ。サイコロの行は無く、「landed on GO」だけが出る。給与 ₼200
    result = replay_log({SELF: 2, AI: 1}, [landed(SELF, "GO")])
    assert result.positions[SELF] == 0 and result.go_passes[SELF] == 1 and result.stopped is None


def test_jail_failed_rolls_are_counted_and_reset_on_leaving() -> None:
    events: list[ev.LogEvent] = [
        ev.SentToJail(SELF),
        ev.DiceRolled(SELF, 5, doubles=False),
        ev.DiceRolled(SELF, 7, doubles=False),
    ]
    result = replay_log({SELF: 30, AI: 0}, events)
    assert result.jail_fails[SELF] == 2 and SELF in result.in_jail
    out = replay_log(
        {SELF: 10, AI: 0},
        [ev.DiceRolled(SELF, 4, doubles=True)],
        frozenset({SELF}),
        None,
        {SELF: 2},
    )
    assert SELF not in out.jail_fails
