"""Maquis のルール(logic/rules.py)のテスト。

期待値は実機(2026-11-11)の画面とログの観測から手で作った(.steering/20261111-phase-maquis/RESULT.md)。
実装から期待値を作らない。確認していない規則(任務、士気、3地点が埋まったカード)は、テストしない。
"""

from dataclasses import replace

import pytest

from bglm.plugins.maquis.logic.board import default_board
from bglm.plugins.maquis.logic.models import (
    EndPhase,
    MaquisState,
    Phase,
    Place,
    Resolve,
    Resources,
)
from bglm.plugins.maquis.logic.rules import MaquisRules, initial_state

RULES = MaquisRules()
BOARD = default_board()

CARD_GROCER = (
    "grocer",
    "pont_du_nord",
    "black_market_fence",
)  # 3局目 ターン1の1枚目(食料品店に出現)
CARD_FENCE = ("black_market_fence", "parade_street", "slums")  # 2枚目(故買屋に出現)
CARD_SLUMS = ("grocer", "slums", "doctor")  # 3枚目(①に巡回がいるので②の貧民街に出現)


def place(state: MaquisState, where: str, card: tuple[str, str, str]) -> MaquisState:
    """団員を置き、その後に出た巡回を足す(画面での1回の配置)。"""
    state = RULES.apply(state, Place(where))
    return RULES.place_patrol(state, card)


def test_initial_state_matches_new_game() -> None:
    s = initial_state()
    assert (s.turn, s.phase, s.agents_total, s.unplaced) == (1, Phase.PLACEMENT, 3, 3)
    assert s.deck.size() == 10
    assert s.resources == Resources(morale=6)


def test_all_sixteen_locations_and_both_mission_slots_are_open_at_the_start() -> None:
    moves = RULES.legal_moves(initial_state())
    expected = set(BOARD.locations()) | {"mission_a", "mission_b"}
    assert {m.location for m in moves if isinstance(m, Place)} == expected
    assert not any(isinstance(m, EndPhase) for m in moves)  # 全員を置くまで、終了ボタンは出ない


def test_cannot_place_on_patrol_or_on_another_agent() -> None:
    # 観測: 巡回のいる地点には置けない(配置ボタンが出ない)。団員は別々の地点へ
    s = place(initial_state(), "field_e", CARD_GROCER)
    spots = {m.location for m in RULES.legal_moves(s) if isinstance(m, Place)}
    assert "grocer" not in spots  # 巡回
    assert "field_e" not in spots  # 自分の団員


def test_end_phase_appears_only_after_every_agent_is_placed() -> None:
    s = initial_state()
    s = place(s, "field_e", CARD_GROCER)
    s = place(s, "field_w", CARD_FENCE)
    assert RULES.legal_moves(s) != [EndPhase()]
    s = place(s, "cafe", CARD_SLUMS)
    assert s.unplaced == 0
    assert RULES.legal_moves(s) == [EndPhase()]


def test_turn_1_of_game_3_ends_with_nobody_captured() -> None:
    # 観測(3局目): 畑(右)・畑(左)・カフェに置き、巡回は食料品店・故買屋・貧民街。次のターンの開始時は 3/3、山札は7枚
    s = initial_state()
    s = place(s, "field_e", CARD_GROCER)
    s = place(s, "field_w", CARD_FENCE)
    s = place(s, "cafe", CARD_SLUMS)
    assert s.patrols == {"grocer", "black_market_fence", "slums"}
    s = RULES.apply(s, EndPhase())  # → 行動フェイズ
    assert s.phase is Phase.ACTION
    s = RULES.apply(s, EndPhase())  # → ターン2
    assert (s.turn, s.phase, s.unplaced, s.agents_total) == (2, Phase.PLACEMENT, 3, 3)
    assert not s.defeated
    assert s.patrols == frozenset()
    assert s.deck.size() == 7


def test_all_agents_stranded_loses_at_end_of_turn() -> None:
    # 観測(2局目 ターン1): 団員が 無線B・医者・無線A、巡回が闇市・食料品店・ポン・レヴェック。
    # 隠れ家の出口がカフェと畑(右)だけになり、3人とも戻れず捕縛 → レジスタンス壊滅
    s = replace(
        initial_state(),
        phase=Phase.ACTION,
        unplaced=0,
        agents=("doctor", "radio_a", "radio_b"),
        patrols=frozenset({"black_market", "grocer", "pont_leveque"}),
    )
    s = RULES.apply(s, EndPhase())
    assert s.defeated
    assert RULES.outcome(s) == "lose"
    assert RULES.is_terminal(s)
    assert RULES.legal_moves(s) == []


def test_one_captured_agent_is_not_a_defeat() -> None:
    # 観測: 1人が帰還できなくても、ほかの団員が戻れればゲームは続く(1局目 ターン1で工場破壊の団員が捕縛された)
    s = replace(
        initial_state(),
        phase=Phase.ACTION,
        unplaced=0,
        agents=("cafe", "doctor", "field_e"),
        patrols=frozenset({"black_market", "grocer", "pont_leveque"}),
    )
    s = RULES.apply(s, EndPhase())
    assert not s.defeated
    assert RULES.outcome(s) is None
    assert s.turn == 2


def test_captured_agent_goes_to_prison_and_leaves_the_pool() -> None:
    # 観測(4局目 ターン2): 4人のうち1人が工場破壊で捕縛された。次のターンの開始時は `3/3`、監獄に団員が1人。
    # さらに次のターン(ターン4)も `3/3`のまま、監獄の団員は戻らなかった
    s = replace(
        initial_state(),
        phase=Phase.ACTION,
        unplaced=0,
        agents_total=4,
        agents=("cafe", "field_e", "field_w", "mission_b"),
        patrols=frozenset({"pont_leveque", "grocer", "pont_du_nord"}),
    )
    s = RULES.apply(s, EndPhase())
    assert (s.agents_total, s.unplaced, s.prisoners) == (3, 3, 1)
    assert not s.defeated
    s = RULES.apply(RULES.apply(s, EndPhase()), EndPhase())
    assert (s.agents_total, s.prisoners) == (3, 1)  # 戻らない


def test_mission_slot_does_not_block_a_patrol_on_its_node() -> None:
    # 観測(4局目 ターン2): 任務Bの団員がいるのに、ポン・デュ・ノールに巡回が出現した(カードの①が空き地点でなくても
    # 団員は任務の枠にいて、地点には居ないため)。団員は「帰還できない」となり捕縛された
    s = replace(initial_state(), agents=("mission_b", "black_market_fence"))
    card = (
        "black_market_fence",
        "pont_du_nord",
        "pont_leveque",
    )  # ①は団員がいるので飛ばし、②のポン・デュ・ノール
    s = RULES.place_patrol(s, card)
    assert s.patrols == {"pont_du_nord"}  # 任務Bの団員は、この地点への出現を塞がない
    # 比較: 任務の枠ではなく地点に団員がいれば、②も飛ばされて③のポン・レヴェックに出る
    s2 = replace(initial_state(), agents=("pont_du_nord", "black_market_fence"))
    assert RULES.place_patrol(s2, card).patrols == {"pont_leveque"}


def test_mission_slot_cannot_be_chosen_while_its_node_has_a_patrol() -> None:
    # 仮定(未確認): 巡回のいる地点の任務の枠には置けないものとして、合法手から外す
    s = replace(initial_state(), patrols=frozenset({"pont_du_nord"}))
    places = {m.location for m in RULES.legal_moves(s) if isinstance(m, Place)}
    assert "mission_b" not in places
    assert "mission_a" in places


def test_mission_b_star_is_lit_even_if_the_agent_cannot_return() -> None:
    # 観測(4局目 ターン2): 「工場破壊で行動したが帰還できない」。★は点灯した(1つ目)。団員は捕縛された
    s = action_state(("mission_b",), frozenset({"pont_leveque", "grocer", "pont_du_nord"}))
    s = RULES.apply(s, Resolve("mission_b", 0))
    assert s.stars == (0, 1)
    assert "mission_b" in s.agents  # 地図に残る


def test_mission_b_second_star_and_agent_returns() -> None:
    # 観測(4局目 ターン3): 巡回が食料品店・故買屋・無線B。任務Bの団員の行動で2つ目の★が点灯し、「帰還した」
    s = replace(
        action_state(("mission_b",), frozenset({"grocer", "black_market_fence", "radio_b"})),
        stars=(0, 1),
    )
    s = RULES.apply(s, Resolve("mission_b", 0))
    assert s.stars == (0, 2)
    assert s.agents == ()
    # 確かめた2つ(団員1人・費用なし)を点灯した後は、実行できない(3つ目は爆薬と団員2人。未確認)
    s2 = replace(action_state(("mission_b",)), stars=(0, 2))
    assert Resolve("mission_b", 0) not in RULES.legal_moves(s2)


def test_stars_stay_after_the_turn_ends() -> None:
    s = replace(action_state(("mission_b",)), stars=(0, 2))
    assert RULES.apply(s, EndPhase()).stars == (0, 2)


def action_state(
    agents: tuple[str, ...], patrols: frozenset[str] = frozenset(), **kw: int
) -> MaquisState:
    return replace(
        initial_state(),
        phase=Phase.ACTION,
        unplaced=0,
        agents=agents,
        patrols=patrols,
        resources=Resources(morale=6, **kw),
    )


def test_doctor_gives_one_medicine_and_the_agent_returns() -> None:
    # 観測(1局目 ターン1): 医者の行動で薬品+1、「マキ団員が医者で行動し帰還した」
    s = action_state(("doctor",))
    assert Resolve("doctor", 0) in RULES.legal_moves(s)
    s = RULES.apply(s, Resolve("doctor", 0))
    assert s.resources.medicine == 1
    assert s.agents == ()
    assert "doctor" in s.acted


def test_grocer_gives_one_food_and_cannot_be_used_twice() -> None:
    s = action_state(("grocer",))
    s = RULES.apply(s, Resolve("grocer", 0))
    assert s.resources.food == 1
    assert Resolve("grocer", 0) not in RULES.legal_moves(s)


def test_resources_are_capped_at_four() -> None:
    # アプリ内ルール「資材」: 上限を超えて集めた資材は失われる
    s = action_state(("doctor",), medicine=4)
    s = RULES.apply(s, Resolve("doctor", 0))
    assert s.resources.medicine == 4


def test_agent_that_cannot_return_still_acts_but_stays_to_be_captured() -> None:
    # 観測(1局目 ターン1): 「工場破壊で行動したが帰還できない」。行動の効果は得て、ターン終了時に捕縛される
    patrols = frozenset({"black_market", "grocer", "pont_leveque"})  # 医者は戻れない
    s = action_state(("doctor", "field_e", "cafe"), patrols)
    s = RULES.apply(s, Resolve("doctor", 0))
    assert s.resources.medicine == 1
    assert "doctor" in s.agents  # 地図に残る
    assert "doctor" in s.acted
    assert RULES.apply(s, EndPhase()).defeated is False  # 1人だけなので敗北ではない


def test_cafe_recruit_needs_food_and_adds_an_agent_from_next_turn() -> None:
    # 観測(1局目 ターン2): 食料1を払って団員が増え、次のターンの開始時は 4/4
    s = action_state(("cafe",))
    assert Resolve("cafe", 0) not in RULES.legal_moves(s)  # 食料が無い
    s = action_state(("cafe",), food=1)
    s = RULES.apply(s, Resolve("cafe", 0))
    assert s.resources.food == 0
    assert s.agents_total == 4
    s = RULES.apply(s, EndPhase())
    assert (s.turn, s.unplaced) == (2, 4)


def test_recruit_stops_at_five_agents() -> None:
    s = replace(action_state(("cafe",), food=1), agents_total=5)
    assert Resolve("cafe", 0) not in RULES.legal_moves(s)


def test_actions_of_unverified_locations_are_not_offered() -> None:
    # 確かめていない地点の行動は、合法手に出さない(推測で埋めない)
    s = action_state(("black_market_fence", "radio_a", "field_w", "grocer"), funds=4, food=4)
    offered = {m.location for m in RULES.legal_moves(s) if isinstance(m, Resolve)}
    assert offered == {"grocer"}


def test_place_patrol_with_all_three_occupied_is_refused() -> None:
    # 3地点とも埋まったカードの扱いは未確認。推測で進めず例外にする
    s = replace(
        initial_state(), agents=("pont_leveque", "black_market"), patrols=frozenset({"radio_a"})
    )
    with pytest.raises(ValueError):
        RULES.place_patrol(s, ("radio_a", "pont_leveque", "black_market"))


def test_diff_ignores_patrols_and_deck_but_reports_agents() -> None:
    s = place(initial_state(), "field_e", CARD_GROCER)
    predicted = RULES.apply(initial_state(), Place("field_e"))
    assert RULES.diff(predicted, s) == {}  # 巡回と山札は予測に含まれないので比べない
    moved = RULES.apply(initial_state(), Place("cafe"))
    assert set(RULES.diff(moved, s)) == {"agents"}


def test_cafe_recruit_stops_when_no_one_is_left_to_recruit() -> None:
    from dataclasses import replace

    from bglm.plugins.maquis.logic.models import Phase, Resolve, Resources

    rules = MaquisRules()
    state = replace(
        initial_state(),
        phase=Phase.ACTION,
        unplaced=0,
        agents=("cafe",),
        resources=Resources(food=2),
        recruits_left=1,
    )
    assert Resolve("cafe", 0) in rules.legal_moves(state)
    after = rules.apply(state, Resolve("cafe", 0))
    assert (after.agents_total, after.recruits_left) == (state.agents_total + 1, 0)
    again = replace(after, agents=("cafe",), acted=frozenset())
    assert Resolve("cafe", 0) not in rules.legal_moves(again)


def test_does_not_use_both_the_mission_slot_and_its_node() -> None:
    from dataclasses import replace

    from bglm.plugins.maquis.logic.models import Place

    rules = MaquisRules()
    base = initial_state()
    on_node = replace(base, agents=("pont_du_nord",), unplaced=2)
    assert Place("mission_b") not in rules.legal_moves(on_node)
    on_slot = replace(base, agents=("mission_b",), unplaced=2)
    assert Place("pont_du_nord") not in rules.legal_moves(on_slot)
    assert Place("mission_b") in rules.legal_moves(base)


def test_new_captive_replaces_the_old_one_and_the_pool_is_unchanged() -> None:
    # 観測(2局目 ターン6・9): 監獄に1人いる状態で、もう1人が捕縛されても `4/4` のまま。
    # 畑(西)は cafe 経由でしか戻れない。cafe に巡回が来ると、畑(西)の団員だけが捕縛される
    s = replace(
        initial_state(),
        phase=Phase.ACTION,
        unplaced=0,
        agents_total=4,
        prisoners=1,
        agents=("field_w",),
        patrols=frozenset({"cafe"}),
    )
    s = RULES.apply(s, EndPhase())
    assert (s.agents_total, s.prisoners, s.defeated) == (4, 1, False)


def test_no_capture_keeps_the_prisoner() -> None:
    s = replace(
        initial_state(), phase=Phase.ACTION, unplaced=0, agents_total=4, prisoners=1, agents=()
    )
    s = RULES.apply(s, EndPhase())
    assert (s.agents_total, s.prisoners) == (4, 1)


def action_with(agents: tuple[str, ...], **resources: int) -> "MaquisState":
    return replace(
        initial_state(),
        phase=Phase.ACTION,
        unplaced=0,
        agents=agents,
        resources=Resources(**resources),
    )


def test_slums_turns_food_and_medicine_into_morale() -> None:
    # 実機(2026-11-15): 食料2→1、薬品2→1、士気4→5
    s = action_with(("slums",), morale=4, food=2, medicine=2)
    assert Resolve("slums", 0) in RULES.legal_moves(s)
    after = RULES.apply(s, Resolve("slums", 0))
    r = after.resources
    assert (r.morale, r.food, r.medicine) == (5, 1, 1)


def test_slums_needs_both_food_and_medicine() -> None:
    s = action_with(("slums",), morale=4, food=2, medicine=0)
    assert Resolve("slums", 0) not in RULES.legal_moves(s)


def test_black_market_sells_food_or_medicine_for_funds_at_a_morale_cost() -> None:
    # 実機: 食料1 → 資金1、士気-1(右列の順は食料、薬品)
    s = action_with(("black_market",), morale=4, food=1, medicine=1)
    r = RULES.apply(s, Resolve("black_market", 0)).resources
    assert (r.funds, r.food, r.medicine, r.morale) == (1, 0, 1, 3)
    r2 = RULES.apply(s, Resolve("black_market", 1)).resources
    assert (r2.funds, r2.food, r2.medicine, r2.morale) == (1, 1, 0, 3)


def test_black_market_is_not_offered_at_the_last_morale() -> None:
    s = action_with(("black_market",), morale=1, food=1)
    assert Resolve("black_market", 0) not in RULES.legal_moves(s)
