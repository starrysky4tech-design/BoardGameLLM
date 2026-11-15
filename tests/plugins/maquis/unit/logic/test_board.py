"""Maquis の盤(logic/board.py)のテスト。

期待値は実機(2026-11-11)の画面の観測から手で作った。「!」は帰還できない地点に付く赤い印。
観測の素材: datasets/raw/maquis/feasibility/(Git管理外)。記録は .steering/20261111-phase-maquis/RESULT.md。
"""

import json
from pathlib import Path

import pytest

from bglm.plugins.maquis.logic.board import Board, default_board, load_board

BOARD = default_board()


def test_board_has_18_nodes_and_one_hideout() -> None:
    # 画面の地点: 17 か所 + 隠れ家(監獄を含めて 18)
    assert len(BOARD.kinds) == 18
    assert BOARD.hideout == "hideout"
    assert BOARD.kinds["prison"] == "prison"
    assert len(BOARD.locations()) == 16  # 隠れ家と監獄は団員を送る先ではない


def test_roads_are_symmetric_and_prison_has_none() -> None:
    for a, near in BOARD.neighbors.items():
        for b in near:
            assert a in BOARD.neighbors[b]
    assert BOARD.neighbors["prison"] == frozenset()


def test_hideout_neighbors() -> None:
    # 隠れ家に道でつながるのは、食料品店・ポン・レヴェック・カフェ・畑(右)
    assert BOARD.neighbors["hideout"] == {"grocer", "pont_leveque", "cafe", "field_e"}


def test_no_patrol_means_everything_reachable() -> None:
    assert BOARD.stranded() == frozenset()


def test_one_patrol_at_grocer_strands_only_south_east_room() -> None:
    # 観測(3局目、1人目の配置後): 巡回が食料品店に出て、「!」が付いたのは右下の空き部屋だけ
    assert BOARD.stranded({"grocer"}) == {"spare_room_se"}


def test_patrols_at_fence_slums_grocer() -> None:
    # 観測(3局目、3人目の配置後): 巡回が故買屋・貧民街・食料品店。「!」は右上側の5か所
    stranded = BOARD.stranded({"black_market_fence", "slums", "grocer"})
    assert stranded == {"pont_du_nord", "radio_b", "black_market", "spare_room_ne", "spare_room_se"}


def test_patrols_at_black_market_grocer_pont_leveque() -> None:
    # 観測(2局目、3人目の配置後): 巡回が闇市・食料品店・ポン・レヴェック。
    # 隠れ家の出口がカフェと畑(右)だけになり、「!」は残りの10か所すべてに付いた
    stranded = BOARD.stranded({"black_market", "grocer", "pont_leveque"})
    assert stranded == {
        "black_market_fence",
        "pont_du_nord",
        "radio_b",
        "parade_street",
        "doctor",
        "slums",
        "spare_room_ne",
        "radio_a",
        "spare_room_w",
        "spare_room_se",
    }


def test_marked_matches_the_red_marks_seen_on_screen() -> None:
    # 観測(4局目 ターン2、4人目の配置後): 巡回が 無線A・食料品店・ポン・レヴェック・ポン・デュ・ノール。
    # 「!」が付いたのは 11 地点(巡回のいる 無線A・ポン・デュ・ノール を含み、隠れ家の隣の 食料品店・ポン・レヴェック は含まない)
    marked = BOARD.marked({"radio_a", "grocer", "pont_leveque", "pont_du_nord"})
    assert marked == {
        "black_market",
        "black_market_fence",
        "doctor",
        "parade_street",
        "pont_du_nord",
        "radio_a",
        "radio_b",
        "slums",
        "spare_room_ne",
        "spare_room_se",
        "spare_room_w",
    }
    # 観測(4局目 ターン3): 巡回が 故買屋・無線B・食料品店 → 右下の空き部屋だけ
    assert BOARD.marked({"black_market_fence", "radio_b", "grocer"}) == {"spare_room_se"}
    # 観測(3局目 ターン3): 巡回が 無線A・医者・故買屋 → バラダ通り・無線A・空き部屋(左)
    assert BOARD.marked({"radio_a", "doctor", "black_market_fence"}) == {
        "parade_street",
        "radio_a",
        "spare_room_w",
    }
    # 観測(4局目 ターン1): 巡回が 無線A・無線B・故買屋 → どこにも「!」が付かない
    assert BOARD.marked({"radio_a", "radio_b", "black_market_fence"}) == frozenset()


def test_cafe_and_fields_next_to_hideout_survive_any_three_patrols() -> None:
    # 観測: カフェと畑(右)は、巡回が3つ来ても「!」が付かなかった。隠れ家のすぐ隣は、巡回が2つまでなら必ず戻れる
    near = ("cafe", "field_e")
    for blocked in ({"grocer", "pont_leveque"}, {"black_market", "grocer", "pont_leveque"}):
        assert not set(near) & BOARD.stranded(blocked)


def test_field_w_is_stranded_only_when_cafe_is_blocked() -> None:
    assert "field_w" in BOARD.stranded({"cafe"})
    assert "field_w" not in BOARD.stranded({"grocer", "pont_leveque"})


def test_hideout_cannot_be_blocked() -> None:
    assert BOARD.reachable_from_hideout({"hideout"}) == BOARD.reachable_from_hideout()


def test_unknown_edge_endpoint_is_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "board.json"
    data = {
        "hideout": "h",
        "nodes": [{"id": "h", "name": "隠れ家", "kind": "hideout"}],
        "edges": [["h", "x"]],
    }
    bad.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        load_board(bad)


def test_board_type() -> None:
    assert isinstance(BOARD, Board)
