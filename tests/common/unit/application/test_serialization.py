import json
from dataclasses import dataclass
from enum import Enum

import pytest

from bglm.application.serialization import jsonable, recognition_to_dict
from bglm.core.models import Recognition, UiKind, UiState


class Color(Enum):
    RED = "red"


@dataclass(frozen=True)
class Inner:
    n: int


@dataclass(frozen=True)
class Outer:
    inner: Inner
    items: tuple[int, ...]
    owners: dict[int, str]
    color: Color


class TestJsonable:
    @pytest.mark.parametrize("value", [None, True, False, 0, -3, 1.5, "日本語"])
    def test_scalars_are_unchanged(self, value: object) -> None:
        assert jsonable(value) == value

    def test_bool_stays_bool(self) -> None:
        assert jsonable(True) is True

    def test_enum_becomes_its_value(self) -> None:
        assert jsonable(Color.RED) == "red"

    def test_dataclass_gets_a_type_name(self) -> None:
        assert jsonable(Inner(3)) == {"type": "Inner", "n": 3}

    def test_nested_structures_are_converted_recursively(self) -> None:
        value = Outer(Inner(1), (1, 2), {3: "me", 4: "opponent"}, Color.RED)

        assert jsonable(value) == {
            "type": "Outer",
            "inner": {"type": "Inner", "n": 1},
            "items": [1, 2],
            "owners": {"3": "me", "4": "opponent"},
            "color": "red",
        }

    def test_result_is_valid_json(self) -> None:
        value = Outer(Inner(1), (1,), {3: "me"}, Color.RED)

        assert json.loads(json.dumps(jsonable(value))) == jsonable(value)

    def test_set_becomes_a_list(self) -> None:
        assert jsonable({7}) == [7]

    def test_unknown_object_falls_back_to_repr(self) -> None:
        assert jsonable(object).startswith("<class")

    def test_dataclass_class_itself_is_not_expanded(self) -> None:
        assert isinstance(jsonable(Inner), str)


class TestRecognitionToDict:
    def test_contains_ui_state_confidence_and_low_confidence(self) -> None:
        recognition = Recognition(
            UiState(UiKind.PLAYABLE, "my_turn"),
            state=Inner(1),
            confidence=0.9,
            low_confidence=("hand",),
        )

        assert recognition_to_dict(recognition) == {
            "ui": {"kind": "playable", "screen": "my_turn"},
            "state": {"type": "Inner", "n": 1},
            "confidence": 0.9,
            "low_confidence": ["hand"],
        }

    def test_missing_state_is_null(self) -> None:
        recognition = Recognition(UiState(UiKind.UNKNOWN, "?"), state=None, confidence=0.0)

        assert recognition_to_dict(recognition)["state"] is None
