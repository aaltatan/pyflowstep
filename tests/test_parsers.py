from datetime import date
from decimal import Decimal
from enum import StrEnum
from inspect import signature
from typing import Annotated, Any

import pytest

from pyflowstep import (
    Depends,
    InvalidParserError,
    MissingArgumentError,
    Parse,
    ParseArgumentError,
    step,
    tap,
)
from pyflowstep.parsers import find_parsers, input_annotation, parse_arguments


class Milk(StrEnum):
    OAT = "oat"
    SOY = "soy"


def normalize(text: str) -> str:
    return text.strip().lower()


def load_rows(path: str) -> list[str]:
    return [f"row from {path}"]


type Text = Annotated[str, Parse(normalize)]
type Rows = Annotated[list[str], Parse(load_rows)]


@step
def order(log: list[Any], name: Text, amount: Annotated[int, Parse(int)] = 1) -> list[Any]:
    return [*log, (name, amount)]


class TestParse:
    def test_holds_the_function(self) -> None:
        assert Parse(int).fn is int

    def test_is_immutable_and_comparable(self) -> None:
        assert Parse(int) == Parse(int)
        assert Parse(int) != Parse(float)
        with pytest.raises(AttributeError):
            Parse(int).fn = float  # type: ignore[misc]

    @pytest.mark.parametrize("fn", [None, 5, "int"])
    def test_needs_a_callable(self, fn: Any) -> None:
        with pytest.raises(InvalidParserError, match="Parse needs a callable"):
            Parse(fn)


class TestParsingArguments:
    def test_positional_and_keyword(self) -> None:
        assert order(" Tea ", "2")([]) == [("tea", 2)]
        assert order(name=" Tea ", amount="2")([]) == [("tea", 2)]

    def test_defaults_are_not_parsed(self) -> None:
        @step
        def pour(log: list[Any], ml: Annotated[int, Parse(int)] = "a lot") -> list[Any]:  # type: ignore[assignment]
            return [*log, ml]

        assert pour()([]) == ["a lot"]

    def test_unmarked_arguments_are_untouched(self) -> None:
        marker = object()

        @step
        def keep(log: list[Any], value: object, amount: Annotated[int, Parse(int)]) -> list[Any]:
            return [*log, value, amount]

        assert keep(marker, "3")([]) == [marker, 3]

    def test_alias_is_reused_across_steps(self) -> None:
        @step
        def first(log: list[Any], rows: Rows) -> list[Any]:
            return [*log, *rows]

        @step
        def second(log: list[Any], label: Text, rows: Rows) -> list[Any]:
            return [*log, label, *rows]

        flow = first("a.csv") >> second(" B ", "b.csv")
        assert flow([]) == ["row from a.csv", "b", "row from b.csv"]

    def test_chained_parsers_run_left_to_right(self) -> None:
        @step
        def tag(
            log: list[Any], value: Annotated[str, Parse(str.strip), Parse(str.upper), Parse(list)]
        ) -> list[Any]:
            return [*log, value]

        assert tag(" ab ")([]) == [["A", "B"]]

    def test_var_positional_parses_each_item(self) -> None:
        @step
        def top(log: list[Any], *toppings: Text) -> list[Any]:
            return [*log, *toppings]

        assert top(" Foam", "COCOA ")([]) == ["foam", "cocoa"]
        assert top()([]) == []

    def test_var_keyword_parses_each_value(self) -> None:
        @step
        def where(
            log: list[Any], *, strict: Annotated[bool, Parse(bool)] = False, **fields: Text
        ) -> list[Any]:
            return [*log, strict, fields]

        assert where(strict=1, brand=" SONIC ", color="Red")([]) == [
            True,
            {"brand": "sonic", "color": "red"},
        ]

    def test_other_annotated_metadata_is_ignored(self) -> None:
        @step
        def add(total: int, amount: Annotated[int, "documentation", Parse(int), 42]) -> int:
            return total + amount

        assert add("2")(1) == 3

    def test_string_annotations(self) -> None:
        @step
        def later(log: list[Any], name: "Text") -> list[Any]:
            return [*log, name]

        assert later(" X ")([]) == ["x"]

    @pytest.mark.parametrize(
        ("parser", "raw", "expected"),
        [
            (Decimal, "2.50", Decimal("2.50")),
            (date.fromisoformat, "2026-10-09", date(2026, 10, 9)),
            (Milk, "oat", Milk.OAT),
            (lambda value: value * 2, 21, 42),
        ],
    )
    def test_any_callable_can_parse(self, parser: Any, raw: Any, expected: Any) -> None:
        @step
        def keep(log: list[Any], value: Annotated[Any, Parse(parser)]) -> list[Any]:
            return [*log, value]

        assert keep(raw)([]) == [expected]

    def test_tap(self) -> None:
        seen: list[str] = []

        @tap
        def remember(_: object, value: Text) -> None:
            seen.append(value)

        remember("  V ")(None)
        assert seen == ["v"]

    def test_factory_signature_keeps_the_parameter(self) -> None:
        assert list(signature(order).parameters) == ["name", "amount"]


class TestWhenParsingHappens:
    def test_once_when_the_step_is_built(self) -> None:
        calls: list[str] = []

        def load(path: str) -> str:
            calls.append(path)
            return path.upper()

        @step
        def use(log: list[Any], data: Annotated[str, Parse(load)]) -> list[Any]:
            return [*log, data]

        flow = use("a.csv")
        assert calls == ["a.csv"]

        assert flow([]) == ["A.CSV"]
        assert flow([]) == ["A.CSV"]
        assert calls == ["a.csv"]

    def test_bad_arguments_fail_before_parsing(self) -> None:
        calls: list[Any] = []

        @step
        def use(log: list[Any], data: Annotated[str, Parse(calls.append)], other: str) -> list[Any]:
            return log

        with pytest.raises(MissingArgumentError, match="'other'"):
            use("x")
        assert calls == []


class TestFailures:
    def test_failure_names_the_argument_and_value(self) -> None:
        with pytest.raises(
            ParseArgumentError, match="Argument 'amount' with value 'two' failed to parse"
        ) as info:
            order("tea", "two")

        assert isinstance(info.value.__cause__, ValueError)

    def test_failure_is_a_type_error(self) -> None:
        with pytest.raises(TypeError):
            order("tea", "two")

    def test_failure_inside_var_positional(self) -> None:
        @step
        def total(log: list[Any], *amounts: Annotated[int, Parse(int)]) -> list[Any]:
            return [*log, sum(amounts)]

        with pytest.raises(ParseArgumentError, match="Argument 'amounts' with value 'x'"):
            total("1", "x")

    def test_failure_inside_var_keyword_names_the_key(self) -> None:
        @step
        def where(log: list[Any], **fields: Text) -> list[Any]:
            return log

        with pytest.raises(ParseArgumentError, match="Argument 'brand' with value 5"):
            where(brand=5)

    def test_failure_in_the_second_parser_reports_the_original_value(self) -> None:
        @step
        def count(log: list[Any], n: Annotated[int, Parse(str.strip), Parse(int)]) -> list[Any]:
            return log

        with pytest.raises(ParseArgumentError, match="Argument 'n' with value ' x '"):
            count(" x ")


class TestInvalidDeclarations:
    def test_marker_as_default_value(self) -> None:
        def bad(log: list[Any], amount: int = Parse(int)) -> list[Any]:  # type: ignore[assignment]
            return log

        with pytest.raises(
            InvalidParserError, match=r"uses Parse as the default of 'amount'.*Annotated"
        ):
            step(bad)

    def test_subject_cannot_be_parsed(self) -> None:
        def bad(log: Text, amount: int) -> str:
            return log

        with pytest.raises(InvalidParserError, match="'bad' cannot parse its subject 'log'"):
            step(bad)

    def test_parse_and_depends_on_one_parameter(self) -> None:
        def bad(
            log: list[Any], unit: Annotated[str, Parse(normalize)] = Depends(lambda: "kg")
        ) -> list[Any]:
            return log

        with pytest.raises(InvalidParserError, match=r"cannot both parse and inject \['unit'\]"):
            step(bad)

    def test_parse_and_depends_on_different_parameters(self) -> None:
        @step
        def weigh(
            log: list[Any], amount: Annotated[int, Parse(int)], unit: str = Depends(lambda: "kg")
        ) -> list[Any]:
            return [*log, f"{amount}{unit}"]

        assert weigh("5")([]) == ["5kg"]

    def test_invalid_parser_error_is_a_type_error(self) -> None:
        assert issubclass(InvalidParserError, TypeError)


class TestHelpers:
    def test_find_parsers(self) -> None:
        def fn(
            subject: object, a: Text, b: int, c: Annotated[int, Parse(int), Parse(abs)] = 0
        ) -> None: ...

        assert find_parsers(fn, "fn") == {
            "a": (Parse(normalize),),
            "c": (Parse(int), Parse(abs)),
        }

    def test_parse_arguments_returns_new_bound_arguments(self) -> None:
        def fn(a: str, b: str = "") -> None: ...

        bound = signature(fn).bind(" A ")
        parsed = parse_arguments({"a": (Parse(normalize),)}, bound)

        assert parsed.arguments == {"a": "a"}
        assert bound.arguments == {"a": " A "}
        assert parsed.args == ("a",)

    @pytest.mark.parametrize(
        ("parser", "expected"),
        [
            (load_rows, str),
            (normalize, str),
            (int, None),
            (str.strip, None),
            (lambda value: value, None),
            (lambda: None, None),
        ],
    )
    def test_input_annotation(self, parser: Any, expected: Any) -> None:
        assert input_annotation(Parse(parser)) is expected
