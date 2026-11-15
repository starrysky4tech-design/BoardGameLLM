"""実行ログ(runs/*/steps/*/step.json)に保存した状態から、`MaquisState` を復元する(対局の途中からの再開)。

認識器は、直前の状態が無いと対局の開始直後とみなして照合する(山札を画面から全部は読めないため)。
途中で止まった対局は、止まる直前に保存した状態を渡して続ける(`MaquisRecognizer(resume=...)`)。
"""

import json
from pathlib import Path
from typing import Any

from bglm.plugins.maquis.logic.models import START_RECRUITS, MaquisState, Phase, Resources
from bglm.plugins.maquis.logic.patrol import PatrolCard, PatrolDeck


def state_from_dict(data: dict[str, Any]) -> MaquisState:
    """`StepRecord` の `recognition.state`(JSON)から復元する。"""
    deck = PatrolDeck(
        tuple(
            (_card(card), int(n))
            for card, n in sorted(data["deck"]["remaining"], key=lambda e: _card(e[0]))
        )
    )
    resources = Resources(**{k: int(v) for k, v in data["resources"].items() if k != "type"})
    stars = data["stars"]
    return MaquisState(
        turn=int(data["turn"]),
        phase=Phase(data["phase"]),
        agents_total=int(data["agents_total"]),
        unplaced=int(data["unplaced"]),
        prisoners=int(data["prisoners"]),
        agents=tuple(data["agents"]),
        acted=frozenset(data["acted"]),
        patrols=frozenset(data["patrols"]),
        deck=deck,
        resources=resources,
        stars=(int(stars[0]), int(stars[1])),
        defeated=bool(data["defeated"]),
        recruits_left=int(data.get("recruits_left", START_RECRUITS)),
    )


def state_from_step_file(path: Path) -> MaquisState:
    record = json.loads(path.read_text(encoding="utf-8"))
    state = record["recognition"]["state"]
    if state is None:
        raise ValueError(f"状態が保存されていない: {path}")
    return state_from_dict(state)


def _card(raw: list[str]) -> PatrolCard:
    if len(raw) != 3:
        raise ValueError(f"巡回カードは3地点: {raw}")
    return (raw[0], raw[1], raw[2])
