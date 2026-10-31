from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

from bglm.core.models import (
    ExecutionResult,
    Frame,
    Recognition,
    TimeBudget,
    UiKind,
    UiState,
    VlmProfile,
)
from bglm.core.protocols import GameIo, GamePlugin, MoveExecutor, Recognizer, Rules, Strategy


class FakeRecognizer:
    def observe(self, io: GameIo, previous: int | None) -> Recognition[int]:
        return Recognition(UiState(UiKind.PLAYABLE, "fake"), state=1, confidence=1.0)

    def debug_overlay(self, frame: Frame, result: Recognition[int]) -> NDArray[np.uint8]:
        return frame.image


class FakeRules:
    def legal_moves(self, state: int) -> list[str]:
        return ["a", "b"]

    def apply(self, state: int, move: str) -> int:
        return state + 1

    def is_terminal(self, state: int) -> bool:
        return state >= 3

    def diff(self, predicted: int, actual: int) -> dict[str, object]:
        return {} if predicted == actual else {"state": (predicted, actual)}


class FakeStrategy:
    def choose(self, state: int, legal: Sequence[str], budget: TimeBudget) -> str:
        return legal[0]


class FakeExecutor:
    def execute(self, io: GameIo, state: int, move: str) -> ExecutionResult:
        return ExecutionResult(success=True)


class PluginMethods:
    """GamePlugin のメソッドだけを持つ。name は持たない。"""

    def recognizer(self) -> Recognizer[int]:
        return FakeRecognizer()

    def rules(self) -> Rules[int, str]:
        return FakeRules()

    def strategy(self) -> Strategy[int, str]:
        return FakeStrategy()

    def executor(self) -> MoveExecutor[int, str]:
        return FakeExecutor()

    def vlm_profile(self) -> VlmProfile | None:
        return None


class FakePlugin(PluginMethods):
    name = "fake"


class NamelessPlugin(PluginMethods):
    pass


class IncompletePlugin:
    name = "incomplete"

    def recognizer(self) -> Recognizer[int]:
        return FakeRecognizer()


def test_complete_plugin_satisfies_protocol() -> None:
    assert isinstance(FakePlugin(), GamePlugin)


def test_plugin_missing_methods_does_not_satisfy_protocol() -> None:
    assert not isinstance(IncompletePlugin(), GamePlugin)


def test_plugin_without_name_does_not_satisfy_protocol() -> None:
    assert not isinstance(NamelessPlugin(), GamePlugin)


def test_fake_plugin_runs_one_step_without_a_screen() -> None:
    plugin = FakePlugin()
    state = 1

    legal = plugin.rules().legal_moves(state)
    move = plugin.strategy().choose(state, legal, TimeBudget(1.0))
    predicted = plugin.rules().apply(state, move)

    assert move == "a"
    assert plugin.rules().diff(predicted, 2) == {}
