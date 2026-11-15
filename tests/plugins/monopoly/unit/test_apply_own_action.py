"""自分の建設の反映。均等建設の規則があるので、土地ごとにまとめず 1 周ずつ足す(2026-11-10 の不具合)。"""

from types import SimpleNamespace

from bglm.plugins.monopoly import runtime
from bglm.plugins.monopoly.logic.models import Holding, MonopolyState, Player

RED = ("Kentucky Avenue", "Indiana Avenue", "Illinois Avenue")


def test_build_two_houses_on_one_square_respects_even_building() -> None:
    state = MonopolyState(
        cash={Player.SELF: 1000, Player.AI: 1000},
        holdings={
            "Illinois Avenue": Holding(owner=Player.SELF, houses=1),
            "Kentucky Avenue": Holding(owner=Player.SELF, houses=1),
            "Indiana Avenue": Holding(owner=Player.SELF),
        },
    )
    agent = SimpleNamespace(state=state)
    runtime._apply_own_action(agent, "build", {"Illinois Avenue": 1, "Indiana Avenue": 2})  # type: ignore[arg-type]
    houses = {n: agent.state.holdings[n].houses for n in RED}
    assert houses == {"Illinois Avenue": 2, "Indiana Avenue": 2, "Kentucky Avenue": 1}
    assert agent.state.cash[Player.SELF] == 1000 - 3 * 150
