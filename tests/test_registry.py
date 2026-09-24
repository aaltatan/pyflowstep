from inspect import signature
from typing import Any

import pytest

from pyflowstep import (
    Flow,
    InvalidProcessorsError,
    InvalidStepError,
    InvalidStepNameError,
    MissingArgumentError,
    ProcessArgumentError,
    StepAlreadyRegisteredError,
    StepDoesNotExistError,
    StepsRegistry,
)


@pytest.fixture
def registry() -> StepsRegistry[list[int]]:
    registry = StepsRegistry[list[int]]()

    @registry.step()
    def push(stack: list[int], value: int) -> list[int]:
        """Push a value."""
        return [*stack, value]

    @registry.step(name="pop")
    def pop_last(stack: list[int]) -> list[int]:
        return stack[:-1]

    @registry.step(hidden=True)
    def clear(_: list[int]) -> list[int]:
        return []

    return registry


class TestLookup:
    def test_steps_lists_visible_steps(self, registry: StepsRegistry[list[int]]) -> None:
        assert list(registry.steps) == ["push", "pop"]

    def test_steps_is_read_only(self, registry: StepsRegistry[list[int]]) -> None:
        with pytest.raises(TypeError):
            registry.steps["x"] = registry["push"]  # type: ignore[index]

    def test_getitem_returns_the_factory(self, registry: StepsRegistry[list[int]]) -> None:
        flow = registry["push"](1) >> registry["push"](2) >> registry["pop"]()
        assert isinstance(flow, Flow)
        assert flow([]) == [1]

    def test_mapping_protocol(self, registry: StepsRegistry[list[int]]) -> None:
        assert "push" in registry
        assert "missing" not in registry
        assert list(registry) == ["push", "pop"]
        assert len(registry) == 2

    def test_unknown_step(self, registry: StepsRegistry[list[int]]) -> None:
        with pytest.raises(StepDoesNotExistError, match=r"'nope' does not exist.*pop, push"):
            registry["nope"]

    def test_unknown_step_is_a_lookup_error(self, registry: StepsRegistry[list[int]]) -> None:
        with pytest.raises(LookupError):
            registry["nope"]


class TestHiddenSteps:
    def test_hidden_step_is_not_visible(self, registry: StepsRegistry[list[int]]) -> None:
        assert "clear" not in registry.steps
        assert "clear" not in registry

    def test_hidden_step_cannot_be_looked_up(self, registry: StepsRegistry[list[int]]) -> None:
        with pytest.raises(StepDoesNotExistError):
            registry["clear"]

    def test_hidden_step_name_is_still_reserved(self, registry: StepsRegistry[list[int]]) -> None:
        with pytest.raises(StepAlreadyRegisteredError):
            registry.register(lambda stack: stack, name="clear")

    def test_decorated_hidden_step_is_usable_from_python(self) -> None:
        registry = StepsRegistry[list[int]]()

        @registry.step(hidden=True)
        def clear(_: list[int]) -> list[int]:
            return []

        assert clear()([1, 2]) == []


class TestRegistration:
    def test_decorator_returns_the_factory(self) -> None:
        registry = StepsRegistry[int]()

        @registry.step()
        def add(total: int, amount: int) -> int:
            return total + amount

        assert add is registry["add"]
        assert add(2)(1) == 3

    def test_register_without_decorator(self) -> None:
        registry = StepsRegistry[int]()
        negate = registry.register(lambda n: -n, name="negate", description="Flip the sign.")

        assert registry["negate"] is negate
        assert negate.__doc__ == "Flip the sign."
        assert negate()(3) == -3

    def test_description_overrides_docstring(self) -> None:
        registry = StepsRegistry[int]()

        @registry.step(description="Custom.")
        def noop(n: int) -> int:
            """Original."""
            return n

        assert noop.__doc__ == "Custom."

    def test_docstring_is_kept(self, registry: StepsRegistry[list[int]]) -> None:
        assert registry["push"].__doc__ == "Push a value."

    def test_duplicate_name(self, registry: StepsRegistry[list[int]]) -> None:
        with pytest.raises(StepAlreadyRegisteredError, match="'push' is already registered"):
            registry.register(lambda stack: stack, name="push")

    def test_failed_registration_leaves_registry_unchanged(self) -> None:
        registry = StepsRegistry[int]()

        with pytest.raises(InvalidStepError):
            registry.register(lambda: 0, name="broken")

        assert "broken" not in registry
        registry.register(lambda n: n, name="broken")  # the name is still free

    @pytest.mark.parametrize("name", ["with space", "1st", "dash-name", ""])
    def test_invalid_names(self, name: str) -> None:
        with pytest.raises(InvalidStepNameError):
            StepsRegistry[int]().register(lambda n: n, name=name)

    def test_lambda_without_name(self) -> None:
        with pytest.raises(InvalidStepNameError):
            StepsRegistry[int]().register(lambda n: n)

    def test_processors(self) -> None:
        registry = StepsRegistry[int]()

        @registry.step(processors=int)
        def add(total: int, amount: int) -> int:
            return total + amount

        assert add("5")(1) == 6

    def test_tap(self) -> None:
        registry = StepsRegistry[list[str]]()
        seen: list[str] = []

        @registry.tap(name="log", description="Log the stack.")
        def log_stack(stack: list[str], prefix: str) -> None:
            seen.append(f"{prefix}{stack}")

        stack = ["a"]
        assert registry["log"](">")(stack) is stack
        assert seen == [">['a']"]
        assert registry["log"].__doc__ == "Log the stack."

    def test_registries_are_independent(self) -> None:
        first, second = StepsRegistry[int](), StepsRegistry[int]()
        first.register(lambda n: n, name="same")
        second.register(lambda n: n, name="same")
        assert first["same"] is not second["same"]


class TestNaming:
    def test_registered_name_is_shown_in_repr(self, registry: StepsRegistry[list[int]]) -> None:
        assert repr(registry["pop"]()) == "Flow(pop)"

    def test_registered_name_is_used_in_argument_errors(self) -> None:
        registry = StepsRegistry[int]()
        registry.register(lambda n, amount: n + amount, name="add")

        with pytest.raises(MissingArgumentError, match="for step 'add'"):
            registry["add"]()

    def test_renaming_keeps_signature_and_docstring(self) -> None:
        registry = StepsRegistry[int]()

        @registry.step(name="plus")
        def add(total: int, amount: int = 1) -> int:
            """Add an amount."""
            return total + amount

        assert add.__name__ == "plus"
        assert add.__doc__ == "Add an amount."
        assert str(signature(add)) == "(amount: int = 1)"
        assert add()(1) == 2

    def test_same_name_is_not_wrapped(self) -> None:
        registry = StepsRegistry[int]()

        def double(n: int) -> int:
            return n * 2

        factory = registry.register(double, name="double")
        assert factory.__wrapped__ is double  # type: ignore[attr-defined]


class TestRegistryProcessors:
    def test_named_processor_applies_to_positional_and_keyword(self) -> None:
        registry = StepsRegistry[int]()

        @registry.step(processors={"amount": int})
        def add(total: int, amount: int) -> int:
            return total + amount

        assert add("2")(1) == 3
        assert add(amount="2")(1) == 3

    def test_processors_run_once_per_factory_call(self) -> None:
        calls: list[Any] = []

        def spy(value: Any) -> Any:
            calls.append(value)
            return value

        registry = StepsRegistry[int]()
        add = registry.register(lambda n, x: n + x, name="add", processors=spy)

        flow = add(1)
        flow(0)
        flow(0)
        assert calls == [1]

    def test_failing_processor(self) -> None:
        registry = StepsRegistry[int]()

        @registry.step(processors={"amount": int})
        def add(total: int, amount: int) -> int:
            return total + amount

        with pytest.raises(
            ProcessArgumentError, match="Argument 'amount' with value 'two'"
        ) as info:
            add("two")
        assert isinstance(info.value.__cause__, ValueError)

    def test_bad_arguments_fail_before_processing(self) -> None:
        registry = StepsRegistry[int]()
        calls: list[Any] = []
        add = registry.register(
            lambda n, x: n + x,
            name="add",
            processors=calls.append,
        )

        with pytest.raises(MissingArgumentError, match="for step 'add'"):
            add()
        assert calls == []

    def test_processed_factory_keeps_signature(self) -> None:
        registry = StepsRegistry[int]()

        @registry.step(processors=int)
        def add(total: int, amount: int) -> int:
            return total + amount

        assert str(signature(add)) == "(amount: int)"

    def test_tap_with_processors(self) -> None:
        registry = StepsRegistry[list[str]]()
        seen: list[str] = []

        @registry.tap(processors=str.strip)
        def remember(_: list[str], value: str) -> None:
            seen.append(value)

        subject: list[str] = []
        assert remember("  v  ")(subject) is subject
        assert seen == ["v"]

    def test_named_processor_leaves_other_arguments_untouched(self) -> None:
        registry = StepsRegistry[list[Any]]()

        @registry.step(processors={"timeout": float})
        def wait(log: list[Any], selector: Any, timeout: float = 5.0) -> list[Any]:
            return [*log, selector, timeout]

        marker = object()
        assert wait(marker, "10")([]) == [marker, 10.0]

    def test_ellipsis_covers_the_remaining_arguments(self) -> None:
        registry = StepsRegistry[list[Any]]()

        @registry.step(processors={"pumps": int, ...: str.lower})
        def add_syrup(log: list[Any], flavor: str, pumps: int = 1) -> list[Any]:
            return [*log, flavor, pumps]

        assert add_syrup("VANILLA", "2")([]) == ["vanilla", 2]
        assert add_syrup("MINT")([]) == ["mint", 1]

    def test_typo_fails_at_registration(self) -> None:
        registry = StepsRegistry[int]()

        with pytest.raises(InvalidProcessorsError, match=r"'wait'.*\['timout'\]"):

            @registry.step(processors={"timout": float})
            def wait(n: int, timeout: float = 5.0) -> int:
                return n

        assert "wait" not in registry

    def test_subject_cannot_be_processed(self) -> None:
        registry = StepsRegistry[int]()

        with pytest.raises(InvalidProcessorsError, match=r"\['total'\]"):
            registry.register(
                lambda total, amount: total + amount, name="add", processors={"total": int}
            )

    def test_old_tuple_form_is_rejected(self) -> None:
        registry = StepsRegistry[int]()

        with pytest.raises(InvalidProcessorsError, match="must be a callable or a mapping"):
            registry.register(lambda n, x: n, name="add", processors=(int, {}))  # type: ignore[arg-type]

    def test_no_processors_means_no_wrapper(self) -> None:
        registry = StepsRegistry[int]()

        def double(n: int) -> int:
            return n * 2

        assert registry.register(double).__wrapped__ is double  # type: ignore[attr-defined]
