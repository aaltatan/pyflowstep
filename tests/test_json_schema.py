from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum, StrEnum
from typing import Annotated, Any, Literal, NotRequired, TypedDict
from uuid import UUID

import pytest

from pyflowstep import (
    StepsRegistry,
    get_flow_json_schema,
    get_json_schema,
    get_step_json_schema,
    step,
)


class Color(StrEnum):
    RED = "red"
    BLUE = "blue"


class Priority(Enum):
    LOW = 1
    HIGH = 2


class Address(TypedDict):
    city: str
    zip: NotRequired[int]


type Size = Literal["S", "M", "L"]


class TestGetJsonSchema:
    @pytest.mark.parametrize(
        ("annotation", "expected"),
        [
            (str, {"type": "string"}),
            (int, {"type": "integer"}),
            (float, {"type": "number"}),
            (Decimal, {"type": "number"}),
            (bool, {"type": "boolean"}),
            (None, {"type": "null"}),
            (type(None), {"type": "null"}),
            (datetime, {"type": "string", "format": "date-time"}),
            (date, {"type": "string", "format": "date"}),
            (time, {"type": "string", "format": "time"}),
            (UUID, {"type": "string", "format": "uuid"}),
            (Any, {}),
            (object, {}),
        ],
    )
    def test_scalars(self, annotation: Any, expected: dict[str, Any]) -> None:
        assert get_json_schema(annotation) == expected

    @pytest.mark.parametrize(
        ("annotation", "expected"),
        [
            (list[int], {"type": "array", "items": {"type": "integer"}}),
            (tuple[str, ...], {"type": "array", "items": {"type": "string"}}),
            (set[float], {"type": "array", "items": {"type": "number"}}),
            (frozenset[bool], {"type": "array", "items": {"type": "boolean"}}),
            (list, {"type": "array", "items": {}}),
            (dict[str, int], {"type": "object", "additionalProperties": {"type": "integer"}}),
            (dict, {"type": "object", "additionalProperties": {}}),
        ],
    )
    def test_containers(self, annotation: Any, expected: dict[str, Any]) -> None:
        assert get_json_schema(annotation) == expected

    def test_literal(self) -> None:
        assert get_json_schema(Literal["a", "b"]) == {"enum": ["a", "b"], "type": "string"}
        assert get_json_schema(Literal[1, "a"]) == {"enum": [1, "a"]}

    def test_enums(self) -> None:
        assert get_json_schema(Color) == {"enum": ["red", "blue"], "type": "string"}
        assert get_json_schema(Priority) == {"enum": [1, 2]}

    def test_unions(self) -> None:
        expected = {"anyOf": [{"type": "string"}, {"type": "null"}]}
        assert get_json_schema(str | None) == expected
        assert get_json_schema(str | None) == get_json_schema(str | None)

    def test_annotated_is_unwrapped(self) -> None:
        assert get_json_schema(Annotated[int, "meta"]) == {"type": "integer"}

    def test_type_alias_is_unwrapped(self) -> None:
        assert get_json_schema(Size) == {"enum": ["S", "M", "L"], "type": "string"}

    def test_typeddict(self) -> None:
        assert get_json_schema(Address) == {
            "type": "object",
            "properties": {"city": {"type": "string"}, "zip": {"type": "integer"}},
            "required": ["city"],
        }

    def test_returns_a_fresh_dict(self) -> None:
        get_json_schema(int)["type"] = "changed"
        assert get_json_schema(int) == {"type": "integer"}


@step
def fill(page: object, selector: str, value: str | int = "", *, delay: float = 0.0) -> object:
    """Type a value into a field."""
    return page


@step
def press(page: object, *keys: str, **modifiers: bool) -> object:
    return page


@step
def pick(page: object, color: Color, /, *, when: date) -> object:
    return page


@step
def raw(page, anything, default=object()):  # type: ignore[no-untyped-def]  # noqa: B008
    return page


class TestGetStepJsonSchema:
    def test_full_schema(self) -> None:
        assert get_step_json_schema("fill", fill) == {
            "type": "object",
            "properties": {
                "name": {"const": "fill"},
                "args": {
                    "type": "array",
                    "prefixItems": [
                        {"type": "string"},
                        {"anyOf": [{"type": "string"}, {"type": "integer"}], "default": ""},
                    ],
                    "items": False,
                },
                "kwargs": {
                    "type": "object",
                    "properties": {
                        "selector": {"type": "string"},
                        "value": {
                            "anyOf": [{"type": "string"}, {"type": "integer"}],
                            "default": "",
                        },
                        "delay": {"type": "number", "default": 0.0},
                    },
                    "required": [],
                    "additionalProperties": False,
                },
            },
            "required": ["name"],
            "additionalProperties": False,
            "description": "Type a value into a field.",
        }

    def test_var_positional_and_var_keyword(self) -> None:
        properties = get_step_json_schema("press", press)["properties"]
        assert properties["args"]["prefixItems"] == []
        assert properties["args"]["items"] == {"type": "string"}
        assert properties["kwargs"]["properties"] == {}
        assert properties["kwargs"]["additionalProperties"] == {"type": "boolean"}

    def test_positional_only_and_required_keyword_only(self) -> None:
        properties = get_step_json_schema("pick", pick)["properties"]
        assert properties["args"]["prefixItems"] == [{"enum": ["red", "blue"], "type": "string"}]
        assert properties["kwargs"]["properties"] == {"when": {"type": "string", "format": "date"}}
        assert properties["kwargs"]["required"] == ["when"]

    def test_unannotated_and_non_json_defaults(self) -> None:
        properties = get_step_json_schema("raw", raw)["properties"]
        assert properties["args"]["prefixItems"] == [{}, {}]

    def test_no_description_without_docstring(self) -> None:
        assert "description" not in get_step_json_schema("press", press)

    def test_uses_the_given_name(self) -> None:
        schema = get_step_json_schema("type_text", fill)
        assert schema["properties"]["name"] == {"const": "type_text"}

    def test_unresolvable_string_annotations_fall_back(self) -> None:
        @step
        def later(page: object, value: "Undefined") -> object:  # type: ignore[name-defined]  # noqa: F821
            return page

        prefix_items = get_step_json_schema("later", later)["properties"]["args"]["prefixItems"]
        assert prefix_items == [{}]

    def test_string_annotations_are_resolved(self) -> None:
        @step
        def count(page: object, times: "int") -> object:
            return page

        prefix_items = get_step_json_schema("count", count)["properties"]["args"]["prefixItems"]
        assert prefix_items == [{"type": "integer"}]


class TestGetFlowJsonSchema:
    def test_schema_of_a_registry(self) -> None:
        registry = StepsRegistry[object]()
        registry.register(lambda page, url: page, name="navigate", description="Go somewhere.")
        registry.register(lambda page: page, name="secret", hidden=True)

        schema = get_flow_json_schema(registry.steps)

        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["type"] == "array"
        (navigate,) = schema["items"]["oneOf"]
        assert navigate["properties"]["name"] == {"const": "navigate"}
        assert navigate["description"] == "Go somewhere."

    def test_empty_registry(self) -> None:
        assert get_flow_json_schema({})["items"] == {"oneOf": []}
