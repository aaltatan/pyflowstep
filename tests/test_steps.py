from functools import partial
from inspect import signature
from typing import Any

import pytest

from pyflowstep import (
    ArgumentError,
    Flow,
    InvalidStepError,
    MissingArgumentError,
    MultipleValuesArgumentError,
    PositionalOnlyArgumentError,
    TooManyArgumentsError,
    UnexpectedKeywordArgumentError,
    step,
    tap,
)


@step
def append(items: list[str], item: str) -> list[str]:
    """Append one item."""
    return [*items, item]


@step
def extend(items: list[str], *new: str, sep: str = "") -> list[str]:
    return [*items, *(f"{sep}{item}" for item in new)]


@step
def label(items: list[str], /, prefix: str = "", *, suffix: str) -> list[str]:
    return [f"{prefix}{item}{suffix}" for item in items]


class TestStepDecorator:
    def test_factory_returns_single_step_flow(self) -> None:
        flow = append("a")
        assert isinstance(flow, Flow)
        assert len(flow) == 1
        assert flow([]) == ["a"]

    def test_steps_compose(self) -> None:
        flow = append("a") >> append("b") >> extend("c", "d", sep="-")
        assert flow([]) == ["a", "b", "-c", "-d"]

    def test_factory_keeps_metadata(self) -> None:
        assert append.__name__ == "append"
        assert append.__doc__ == "Append one item."
        assert append.__wrapped__ is not None  # type: ignore[attr-defined]

    def test_factory_signature_excludes_subject(self) -> None:
        assert str(signature(append)) == "(item: str)"
        assert str(signature(label)) == "(prefix: str = '', *, suffix: str)"

    def test_action_is_named_after_the_step(self) -> None:
        (action,) = append("a").actions
        assert action.__name__ == "append"
        assert action.__doc__ == "Append one item."

    def test_arguments_are_passed_through_unchanged(self) -> None:
        value = object()
        seen: list[object] = []

        @step
        def keep(items: list[str], item: object) -> list[str]:
            seen.append(item)
            return items

        keep(value)([])
        assert seen[0] is value

    def test_lambdas_are_named_after_their_repr(self) -> None:
        assert repr(step(lambda n: n)()) == "Flow(<lambda>)"

    def test_partials(self) -> None:
        add_ten = step(partial(lambda x, n: n + x, 10))
        assert add_ten()(1) == 11
        assert repr(add_ten()).startswith("Flow(functools.partial(")

    def test_each_call_builds_an_independent_flow(self) -> None:
        first, second = append("a"), append("b")
        assert first([]) == ["a"]
        assert second([]) == ["b"]

    def test_mutable_arguments_are_bound_once(self) -> None:
        values = ["x"]
        flow = extend(*values)
        values.append("y")
        assert flow([]) == ["x"]

    def test_runtime_exceptions_propagate(self) -> None:
        @step
        def fail(items: list[str]) -> list[str]:
            raise KeyError(items)

        with pytest.raises(KeyError):
            (append("a") >> fail())([])


class TestArgumentValidation:
    """Arguments are checked when the flow is built, not when it runs."""

    @pytest.mark.parametrize(
        ("build", "error", "message"),
        [
            (append, MissingArgumentError, "missing a required argument: 'item'"),
            (label, MissingArgumentError, "argument: 'suffix'"),
            (lambda: append("a", "b"), TooManyArgumentsError, "too many positional arguments"),
            (lambda: append("a", x="b"), UnexpectedKeywordArgumentError, "unexpected keyword"),
            (
                lambda: append("a", item="b"),
                MultipleValuesArgumentError,
                "multiple values for argument 'item'",
            ),
        ],
    )
    def test_bad_arguments_raise_at_build_time(
        self,
        build: Any,
        error: type[ArgumentError],
        message: str,
    ) -> None:
        with pytest.raises(error, match=message):
            build()

    def test_error_message_names_the_step(self) -> None:
        with pytest.raises(MissingArgumentError, match="for step 'append'"):
            append()

    def test_argument_errors_are_type_errors(self) -> None:
        with pytest.raises(TypeError):
            append()

    def test_positional_only_passed_by_keyword(self) -> None:
        @step
        def pad(text: str, width: int = 1, /) -> str:
            return text.ljust(width)

        with pytest.raises(PositionalOnlyArgumentError, match="positional-only"):
            pad(width=3)

    def test_error_is_chained_to_the_original_type_error(self) -> None:
        with pytest.raises(MissingArgumentError) as info:
            append()
        assert isinstance(info.value.__cause__, TypeError)

    def test_defaults_are_applied_at_run_time(self) -> None:
        assert label(suffix="!")(["a"]) == ["a!"]


class TestTap:
    def test_return_value_is_ignored(self) -> None:
        log: list[str] = []

        @tap
        def record(subject: dict[str, int], key: str) -> str:
            log.append(key)
            return "ignored"

        subject = {"a": 1}
        assert (record("x") >> record("y"))(subject) is subject
        assert log == ["x", "y"]


class TestInvalidSteps:
    def test_function_without_parameters(self) -> None:
        def nothing() -> None: ...

        with pytest.raises(InvalidStepError, match="first positional parameter"):
            step(nothing)

    @pytest.mark.parametrize(
        "fn",
        [
            lambda *subjects: subjects,
            lambda *, subject: subject,
            lambda **subject: subject,
        ],
    )
    def test_subject_must_be_positional(self, fn: Any) -> None:
        with pytest.raises(InvalidStepError, match="first positional parameter, got"):
            step(fn)

    def test_callable_without_signature(self) -> None:
        with pytest.raises(InvalidStepError):
            step(next)  # a builtin without a signature

    def test_invalid_step_error_is_a_type_error(self) -> None:
        assert issubclass(InvalidStepError, TypeError)
