from datetime import date
from inspect import signature
from typing import Any

import pytest

from pyflowstep import InvalidProcessorsError, ProcessArgumentError
from pyflowstep.processors import process_arguments, processor_lookup


def schedule(day: date, /, hour: int, *tags: str, note: str = "", **extra: Any) -> None: ...


def book(room: str, hour: int, note: str = "") -> None: ...


def bind(*args: Any, **kwargs: Any) -> Any:
    return signature(schedule).bind(*args, **kwargs)


def lookup_for(processors: Any, fn: Any = book) -> Any:
    return processor_lookup(processors, signature(fn).parameters, "book")


class TestProcessorLookup:
    def test_callable_applies_to_every_argument(self) -> None:
        lookup = lookup_for(str.strip)
        assert lookup("room") is str.strip
        assert lookup("anything") is str.strip

    def test_mapping_applies_to_named_arguments_only(self) -> None:
        lookup = lookup_for({"hour": int})
        assert lookup("hour") is int
        assert lookup("room") is None

    def test_ellipsis_key_covers_the_remaining_arguments(self) -> None:
        lookup = lookup_for({"hour": int, ...: str.strip})
        assert lookup("hour") is int
        assert lookup("room") is str.strip
        assert lookup("note") is str.strip

    def test_ellipsis_alone_acts_like_a_callable(self) -> None:
        assert lookup_for({...: str.strip})("room") is str.strip

    def test_empty_mapping_processes_nothing(self) -> None:
        assert lookup_for({})("room") is None

    def test_unknown_parameter_is_rejected(self) -> None:
        with pytest.raises(InvalidProcessorsError, match=r"unknown parameters \['huor'\]") as info:
            lookup_for({"huor": int})
        assert "available parameters: room, hour, note" in str(info.value)

    def test_unknown_parameters_are_all_reported(self) -> None:
        with pytest.raises(InvalidProcessorsError, match=r"\['a', 'b'\]"):
            lookup_for({"b": int, "a": int, "hour": int})

    def test_step_without_parameters(self) -> None:
        with pytest.raises(InvalidProcessorsError, match=r"available parameters: \(none\)"):
            lookup_for({"x": int}, lambda: None)

    def test_var_keyword_accepts_any_name(self) -> None:
        lookup = lookup_for({"color": str.upper}, schedule)
        assert lookup("color") is str.upper

    def test_non_callable_processor_is_rejected(self) -> None:
        with pytest.raises(InvalidProcessorsError, match=r"must be callables, not for \['hour'\]"):
            lookup_for({"hour": 5, "room": str})

    @pytest.mark.parametrize("processors", [5, "int", (str, {}), [int]])
    def test_wrong_type_is_rejected(self, processors: Any) -> None:
        with pytest.raises(InvalidProcessorsError, match="must be a callable or a mapping"):
            lookup_for(processors)

    def test_invalid_processors_error_is_a_type_error(self) -> None:
        assert issubclass(InvalidProcessorsError, TypeError)


class TestProcessArguments:
    def test_no_processor_keeps_values(self) -> None:
        bound = bind("2026-01-01", "9", "a", note="n", color="red")
        assert process_arguments(lambda _: None, bound).arguments == bound.arguments

    def test_every_parameter_kind(self) -> None:
        processors = {
            "day": date.fromisoformat,
            "hour": int,
            "tags": str.upper,
            "note": str.strip,
            "color": str.title,
        }
        bound = bind("2026-01-01", "9", "a", "b", note=" hi ", color="red", size="L")

        assert process_arguments(processors.get, bound).arguments == {
            "day": date(2026, 1, 1),
            "hour": 9,
            "tags": ("A", "B"),
            "note": "hi",
            "extra": {"color": "Red", "size": "L"},
        }

    def test_original_bound_arguments_are_untouched(self) -> None:
        bound = bind("2026-01-01", "9")
        process_arguments(lambda _: str.upper, bound)
        assert bound.arguments == {"day": "2026-01-01", "hour": "9"}

    def test_args_and_kwargs_follow_the_signature(self) -> None:
        processed = process_arguments({"hour": int}.get, bind("d", hour="9"))
        assert processed.args == ("d", 9)
        assert processed.kwargs == {}

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"hour": "nine"}, "Argument 'hour' with value 'nine' failed to process"),
            ({"hour": "1", "color": 5}, "Argument 'color' with value 5 failed to process"),
        ],
    )
    def test_failure_names_the_argument(self, kwargs: dict[str, Any], message: str) -> None:
        processors = {"hour": int, "color": str.upper}

        with pytest.raises(ProcessArgumentError, match=message) as info:
            process_arguments(processors.get, bind("d", **kwargs))

        assert info.value.__cause__ is not None

    def test_failure_inside_var_positional(self) -> None:
        with pytest.raises(ProcessArgumentError, match="Argument 'tags' with value 'x'"):
            process_arguments({"tags": int}.get, bind("d", 1, "2", "x"))
