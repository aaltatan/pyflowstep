from typing import Annotated

import pytest
from pyargprocessors import Process

from pyflowstep import (
    Depends,
    FlowCompiler,
    Input,
    InvalidInputError,
    InvalidStepError,
    MissingArgumentError,
    StepAlreadyRegisteredError,
    StepsRegistry,
    get_flow_json_schema,
    override,
    step,
    tap,
)


@step
def fill(items: list[str], selector: str, *, value: str) -> list[str]:
    """Fill a field."""
    return [*items, f"{selector}={value}"]


class TestOverride:
    def test_argument_becomes_input(self) -> None:
        @override(fill)
        def fill_from_input(items: list[str], selector: str, *, value: str = Input()) -> list[str]:
            raise AssertionError

        flow = fill_from_input("#a")

        assert flow.inputs == {"value"}
        assert flow([], value="x") == ["#a=x"]

    def test_argument_becomes_dependency(self) -> None:
        @override(fill)
        def fill_injected(
            items: list[str], selector: str, *, value: str = Depends(lambda: "dep")
        ) -> list[str]:
            raise AssertionError

        assert fill_injected("#a")([]) == ["#a=dep"]

    def test_argument_gets_a_plain_default(self) -> None:
        @override(fill)
        def fill_default(items: list[str], selector: str, *, value: str = "d") -> list[str]:
            raise AssertionError

        assert fill_default("#a")([]) == ["#a=d"]
        assert fill_default("#a", value="v")([]) == ["#a=v"]

    def test_input_becomes_argument(self) -> None:
        @step
        def greet(items: list[str], name: str = Input()) -> list[str]:
            return [*items, name]

        @override(greet)
        def greet_fixed(items: list[str], name: str) -> list[str]:
            raise AssertionError

        assert greet_fixed("Ada").inputs == frozenset()
        assert greet_fixed("Ada")([]) == ["Ada"]

    def test_tap_behaviour_is_kept(self) -> None:
        seen: list[str] = []

        @tap
        def record(items: list[str], label: str) -> None:
            seen.append(label)

        @override(record)
        def record_default(items: list[str], label: str = "x") -> None: ...

        assert record_default()(["a"]) == ["a"]
        assert seen == ["x"]

    def test_override_of_override_runs_the_first_body(self) -> None:
        @override(fill)
        def first(items: list[str], selector: str, *, value: str = "1") -> list[str]:
            raise AssertionError

        @override(first)
        def second(items: list[str], selector: str = "#s", *, value: str = "2") -> list[str]:
            raise AssertionError

        assert second()([]) == ["#s=2"]

    def test_process_repeated_on_the_stub_is_kept(self) -> None:
        @step
        def times(total: int, factor: Annotated[int, Process(int)]) -> int:
            return total * factor

        @override(times)
        def times_two(total: int, factor: Annotated[int, Process(int)] = 2) -> int: ...

        assert times_two("3")(2) == 6

    def test_docstring_is_inherited_or_replaced(self) -> None:
        @override(fill)
        def inherited(items: list[str], selector: str, *, value: str = "") -> list[str]: ...

        @override(fill)
        def replaced(items: list[str], selector: str, *, value: str = "") -> list[str]:
            """Do the replaced thing."""
            raise AssertionError

        assert inherited.__doc__ == "Fill a field."
        assert replaced.__doc__ == "Do the replaced thing."

    def test_stub_name_in_repr_and_errors(self) -> None:
        @override(fill)
        def fill_v(items: list[str], selector: str, *, value: str = Input()) -> list[str]: ...

        assert repr(fill_v("#a")) == "Flow(fill_v)"

        with pytest.raises(MissingArgumentError, match="for step 'fill_v'"):
            fill_v()


class TestOverrideRejections:
    def test_not_a_step_factory(self) -> None:
        def plain(items: list[str]) -> list[str]:
            return items

        with pytest.raises(InvalidStepError, match="'plain' is not a step factory"):
            override(plain)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "stub_source",
        [
            "def v(items, other, *, value=''): ...",
            "def v(items, *, value='', selector=''): ...",
            "def v(items, selector, value=''): ...",
            "def v(items, selector): ...",
        ],
    )
    def test_parameters_differ(self, stub_source: str) -> None:
        namespace: dict[str, object] = {}
        exec(stub_source, namespace)  # noqa: S102

        with pytest.raises(InvalidStepError, match="must keep the parameters of 'fill'"):
            override(fill)(namespace["v"])  # type: ignore[arg-type]

    def test_process_lost(self) -> None:
        @step
        def times(total: int, factor: Annotated[int, Process(int)]) -> int:
            return total * factor

        with pytest.raises(InvalidStepError, match="drops the Process of 'factor'"):

            @override(times)
            def times_two(total: int, factor: int = 2) -> int: ...

    def test_process_replaced_by_input_is_fine(self) -> None:
        @step
        def times(total: int, factor: Annotated[int, Process(int)]) -> int:
            return total * factor

        @override(times)
        def times_input(total: int, factor: int = Input()) -> int: ...

        assert times_input()(2, factor=3) == 6

    def test_positional_only_as_input(self) -> None:
        @step
        def pos(items: list[str], a: str, /) -> list[str]:
            return [*items, a]

        with pytest.raises(InvalidInputError, match="positional-only parameter 'a'"):

            @override(pos)
            def pos_input(items: list[str], a: str = Input(), /) -> list[str]: ...


class TestRegistryOverride:
    @pytest.fixture
    def registry(self) -> StepsRegistry[list[str]]:
        registry = StepsRegistry[list[str]]()
        registry.register(fill.__wrapped__, name="fill")  # type: ignore[attr-defined]
        return registry

    def test_name_description_and_json(self, registry: StepsRegistry[list[str]]) -> None:
        @registry.override(registry["fill"], name="fill_q", description="Fill the search box.")
        def fill_search(items: list[str], selector: str = "#q", *, value: str) -> list[str]: ...

        flow = FlowCompiler(registry.steps).compile([{"name": "fill_q", "kwargs": {"value": "x"}}])

        assert repr(flow) == "Flow(fill_q)"
        assert flow([]) == ["#q=x"]
        assert fill_search.__doc__ == "Fill the search box."

        names = [
            item["properties"]["name"]["const"]
            for item in get_flow_json_schema(registry.steps)["items"]["oneOf"]
        ]
        assert names == ["fill", "fill_q"]

    def test_hidden(self, registry: StepsRegistry[list[str]]) -> None:
        @registry.override(registry["fill"], hidden=True)
        def secret(items: list[str], selector: str, *, value: str = "") -> list[str]: ...

        assert "secret" not in registry
        assert secret("#a")([]) == ["#a="]

    def test_duplicate_name(self, registry: StepsRegistry[list[str]]) -> None:
        with pytest.raises(StepAlreadyRegisteredError):

            @registry.override(registry["fill"], name="fill")
            def again(items: list[str], selector: str, *, value: str = "") -> list[str]: ...
