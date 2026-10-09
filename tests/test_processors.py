from datetime import date
from decimal import Decimal
from enum import StrEnum
from inspect import signature
from typing import Annotated, Any

import pytest
from pyargprocessors import (
    InvalidProcessorError,
    Process,
    ProcessArgumentError,
    each,
    optional,
)

from pyflowstep import (
    Depends,
    MissingArgumentError,
    PyflowstepError,
    step,
    tap,
)


class Milk(StrEnum):
    OAT = "oat"
    SOY = "soy"


def normalize(text: str) -> str:
    return text.strip().lower()


def load_rows(path: str) -> list[str]:
    return [f"row from {path}"]


type Text = Annotated[str, Process(normalize)]
type Rows = Annotated[list[str], Process(load_rows)]


@step
def order(log: list[Any], name: Text, amount: Annotated[int, Process(int)] = 1) -> list[Any]:
    return [*log, (name, amount)]


class TestProcessingArguments:
    def test_positional_and_keyword(self) -> None:
        assert order(" Tea ", "2")([]) == [("tea", 2)]
        assert order(name=" Tea ", amount="2")([]) == [("tea", 2)]

    def test_defaults_are_not_processed(self) -> None:
        @step
        def pour(log: list[Any], ml: Annotated[int, Process(int)] = "a lot") -> list[Any]:  # type: ignore[assignment]
            return [*log, ml]

        assert pour()([]) == ["a lot"]

    def test_unmarked_arguments_are_untouched(self) -> None:
        marker = object()

        @step
        def keep(log: list[Any], value: object, amount: Annotated[int, Process(int)]) -> list[Any]:
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

    def test_chained_processors_run_left_to_right(self) -> None:
        @step
        def tag(
            log: list[Any],
            value: Annotated[str, Process(str.strip), Process(str.upper), Process(list)],
        ) -> list[Any]:
            return [*log, value]

        assert tag(" ab ")([]) == [["A", "B"]]

    def test_var_positional_processes_each_item(self) -> None:
        @step
        def top(log: list[Any], *toppings: Text) -> list[Any]:
            return [*log, *toppings]

        assert top(" Foam", "COCOA ")([]) == ["foam", "cocoa"]
        assert top()([]) == []

    def test_var_keyword_processes_each_value(self) -> None:
        @step
        def where(
            log: list[Any], *, strict: Annotated[bool, Process(bool)] = False, **fields: Text
        ) -> list[Any]:
            return [*log, strict, fields]

        assert where(strict=1, brand=" SONIC ", color="Red")([]) == [
            True,
            {"brand": "sonic", "color": "red"},
        ]

    def test_other_annotated_metadata_is_ignored(self) -> None:
        @step
        def add(total: int, amount: Annotated[int, "documentation", Process(int), 42]) -> int:
            return total + amount

        assert add("2")(1) == 3

    def test_string_annotations(self) -> None:
        @step
        def later(log: list[Any], name: "Text") -> list[Any]:
            return [*log, name]

        assert later(" X ")([]) == ["x"]

    @pytest.mark.parametrize(
        ("processor", "raw", "expected"),
        [
            (Decimal, "2.50", Decimal("2.50")),
            (date.fromisoformat, "2026-10-09", date(2026, 10, 9)),
            (Milk, "oat", Milk.OAT),
            (lambda value: value * 2, 21, 42),
        ],
    )
    def test_any_callable_can_process(self, processor: Any, raw: Any, expected: Any) -> None:
        @step
        def keep(log: list[Any], value: Annotated[Any, Process(processor)]) -> list[Any]:
            return [*log, value]

        assert keep(raw)([]) == [expected]

    def test_each_and_optional(self) -> None:
        @step
        def add(
            log: list[Any],
            amounts: Annotated[list[int], Process(each(int))],
            limit: Annotated[int | None, Process(optional(int))] = None,
        ) -> list[Any]:
            return [*log, amounts, limit]

        assert add(["1", "2"], "3")([]) == [[1, 2], 3]
        assert add(["1"], None)([]) == [[1], None]

    def test_tap(self) -> None:
        seen: list[str] = []

        @tap
        def remember(_: object, value: Text) -> None:
            seen.append(value)

        remember("  V ")(None)
        assert seen == ["v"]

    def test_factory_signature_keeps_the_parameter(self) -> None:
        assert list(signature(order).parameters) == ["name", "amount"]


class TestWhenProcessingHappens:
    def test_once_when_the_step_is_built(self) -> None:
        calls: list[str] = []

        def load(path: str) -> str:
            calls.append(path)
            return path.upper()

        @step
        def use(log: list[Any], data: Annotated[str, Process(load)]) -> list[Any]:
            return [*log, data]

        flow = use("a.csv")
        assert calls == ["a.csv"]

        assert flow([]) == ["A.CSV"]
        assert flow([]) == ["A.CSV"]
        assert calls == ["a.csv"]

    def test_bad_arguments_fail_before_processing(self) -> None:
        calls: list[Any] = []

        @step
        def use(
            log: list[Any], data: Annotated[str, Process(calls.append)], other: str
        ) -> list[Any]:
            return log

        with pytest.raises(MissingArgumentError, match="'other'"):
            use("x")
        assert calls == []


class TestFailures:
    def test_failure_names_the_argument_and_value(self) -> None:
        with pytest.raises(
            ProcessArgumentError, match="Argument 'amount' with value 'two' failed to process"
        ) as info:
            order("tea", "two")

        assert (info.value.argument, info.value.value) == ("amount", "two")
        assert isinstance(info.value.cause, ValueError)
        assert info.value.__cause__ is info.value.cause

    def test_failure_is_a_type_error_of_pyargprocessors(self) -> None:
        with pytest.raises(TypeError) as info:
            order("tea", "two")

        assert not isinstance(info.value, PyflowstepError)

    def test_failure_inside_var_positional(self) -> None:
        @step
        def total(log: list[Any], *amounts: Annotated[int, Process(int)]) -> list[Any]:
            return [*log, sum(amounts)]

        with pytest.raises(ProcessArgumentError, match="Argument 'amounts' with value 'x'"):
            total("1", "x")

    def test_failure_inside_var_keyword_names_the_key(self) -> None:
        @step
        def where(log: list[Any], **fields: Text) -> list[Any]:
            return log

        with pytest.raises(ProcessArgumentError, match="Argument 'brand' with value 5"):
            where(brand=5)

    def test_failure_in_the_second_processor_reports_the_original_value(self) -> None:
        @step
        def count(log: list[Any], n: Annotated[int, Process(str.strip), Process(int)]) -> list[Any]:
            return log

        with pytest.raises(ProcessArgumentError, match="Argument 'n' with value ' x '"):
            count(" x ")


class TestInvalidDeclarations:
    def test_marker_as_default_value(self) -> None:
        def bad(log: list[Any], amount: int = Process(int)) -> list[Any]:  # type: ignore[assignment]
            return log

        with pytest.raises(
            InvalidProcessorError, match=r"uses Process as the default of 'amount'.*Annotated"
        ):
            step(bad)

    def test_subject_cannot_be_processed(self) -> None:
        def bad(log: Text, amount: int) -> str:
            return log

        with pytest.raises(InvalidProcessorError, match="'bad' cannot process 'log': it is not"):
            step(bad)

    def test_process_and_depends_on_one_parameter(self) -> None:
        def bad(
            log: list[Any], unit: Annotated[str, Process(normalize)] = Depends(lambda: "kg")
        ) -> list[Any]:
            return log

        with pytest.raises(
            InvalidProcessorError, match=r"cannot both process and inject \['unit'\]"
        ):
            step(bad)

    def test_process_and_depends_on_different_parameters(self) -> None:
        @step
        def weigh(
            log: list[Any], amount: Annotated[int, Process(int)], unit: str = Depends(lambda: "kg")
        ) -> list[Any]:
            return [*log, f"{amount}{unit}"]

        assert weigh("5")([]) == ["5kg"]
