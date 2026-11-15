"""保存した状態(step.json の recognition.state)から、状態を復元するテスト。"""

from bglm.plugins.maquis.logic.models import Phase
from bglm.plugins.maquis.logic.resume import state_from_dict

SAVED = {
    "type": "MaquisState",
    "turn": 2,
    "phase": "action",
    "agents_total": 3,
    "unplaced": 0,
    "prisoners": 1,
    "agents": ["cafe", "grocer"],
    "acted": ["grocer"],
    "patrols": ["radio_a"],
    "deck": {
        "type": "PatrolDeck",
        "remaining": [
            [["grocer", "slums", "doctor"], 2],
            [["radio_a", "parade_street", "grocer"], 1],
        ],
    },
    "resources": {
        "type": "Resources",
        "morale": 5,
        "food": 1,
        "medicine": 0,
        "funds": 0,
        "intel": 0,
        "guns": 0,
        "explosives": 0,
    },
    "stars": [0, 1],
    "defeated": False,
}


def test_restores_every_field() -> None:
    state = state_from_dict(SAVED)
    assert (state.turn, state.phase, state.prisoners) == (2, Phase.ACTION, 1)
    assert state.agents == ("cafe", "grocer") and state.acted == {"grocer"}
    assert state.patrols == {"radio_a"}
    assert state.deck.size() == 3
    assert state.deck.count(("grocer", "slums", "doctor")) == 2
    assert (state.resources.morale, state.resources.food) == (5, 1)
    assert state.stars == (0, 1)
