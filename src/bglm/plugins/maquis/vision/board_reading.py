"""盤の画面(1枚)から、読めるものを全部読む。状態への組み立て(前の状態との照合)は recognizer.py。

読んだ値どうしの整合も確かめる: 「!」の付いた地点は、巡回の位置から計算した結果(Board.marked)と一致するはず。
一致しなければ、読み取りかルールの誤りを疑って問題として返す(推測で埋めない)。
"""

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from bglm.plugins.maquis.logic.board import Board
from bglm.plugins.maquis.logic.models import Phase, Resources
from bglm.plugins.maquis.vision import layout, nodes
from bglm.plugins.maquis.vision.counters import (
    PhaseIcon,
    mission_kind,
    read_agent_numbers,
    read_phase,
    read_resources,
    read_stars,
)

SUPPORTED_MISSIONS = {
    "mission_a": "spy_support",
    "mission_b": "factory_sabotage",
}  # 実機で確かめた2つ


@dataclass(frozen=True)
class BoardReading:
    phase: Phase
    unplaced: int
    agents_total: int
    agents: tuple[str, ...]  # 団員のいる枠(地点・任務の枠)。昇順
    patrols: frozenset[str]
    prison: bool
    resources: Resources
    stars: tuple[int, int]
    confidence: float


@dataclass(frozen=True)
class ReadResult:
    reading: BoardReading | None
    problems: tuple[str, ...]
    confidence: float
    fatal: bool = False  # 待っても直らない問題(見たことの無い任務など)


def read_board(image: NDArray[np.uint8], board: Board) -> ReadResult:
    problems: list[str] = []
    confidence = 1.0

    icon, icon_conf = read_phase(image)
    if icon is None:
        problems.append("phase")
    confidence = min(confidence, icon_conf if icon else 0.0)

    counts, count_conf = read_agent_numbers(image)
    if counts is None:
        problems.append("agent_counts")
    confidence = min(confidence, count_conf)

    resources = read_resources(image)
    problems += resources.problems

    for slot, expected in SUPPORTED_MISSIONS.items():
        kind, _ = mission_kind(image, slot)
        if kind != expected:
            return ReadResult(None, (f"mission_unknown:{slot}",), 0.0, fatal=True)
    stars = tuple(read_stars(image, slot) for slot in ("mission_a", "mission_b"))
    if not all(contiguous for _, contiguous in stars):
        problems.append("stars_gap")

    agents: list[str] = []
    patrols: set[str] = set()
    prison = False
    for node in layout.NODE_CENTER:
        if node == "hideout":
            continue
        read = nodes.read_node(image, node)
        if read.occupant is None:
            problems.append(read.problem or f"node:{node}")
            continue
        if node == "prison":
            prison = read.occupant is not nodes.Occupant.EMPTY
        elif read.occupant is nodes.Occupant.AGENT:
            agents.append(node)
        elif read.occupant is nodes.Occupant.PATROL:
            patrols.add(node)
    for slot in layout.MISSION_LEFT:
        present, fraction = nodes.mission_has_agent(image, slot)
        if present:
            agents.append(slot)
        elif fraction > 0.3:  # 写真の枠がありそうで、決め切れない(演出の途中)
            problems.append(f"mission_photo:{slot}")

    if not problems:
        problems += _check_marks(image, board, frozenset(patrols))
    if problems or icon is None or counts is None or resources.resources is None:
        return ReadResult(None, tuple(problems), confidence)
    phase = Phase.PLACEMENT if icon is PhaseIcon.BICYCLE else Phase.ACTION
    reading = BoardReading(
        phase=phase,
        unplaced=counts[0],
        agents_total=counts[1],
        agents=tuple(sorted(agents)),
        patrols=frozenset(patrols),
        prison=prison,
        resources=resources.resources,
        stars=(stars[0][0], stars[1][0]),
        confidence=confidence,
    )
    return ReadResult(reading, (), confidence)


def _check_marks(image: NDArray[np.uint8], board: Board, patrols: frozenset[str]) -> list[str]:
    """読んだ「!」が、巡回の位置から計算した結果と一致するか。"""
    bangs = nodes.read_bangs(image)
    seen = nodes.stranded_nodes(bangs)
    expected = board.marked(patrols)
    problems = [] if seen == expected else ["bang_mismatch"]
    mission_seen = nodes.mission_bangs(bangs)
    blocked = patrols | expected
    mission_expected = frozenset(slot for slot, node in board.missions.items() if node in blocked)
    if mission_seen != mission_expected:
        problems.append("mission_bang_mismatch")
    return problems
