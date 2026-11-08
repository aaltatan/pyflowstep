from typing import Annotated, Any

import pytest
from pyargprocessors import Process

from pyflowstep import (
    Depends,
    Flow,
    FlowCompiler,
    Input,
    InvalidStepError,
    MissingArgumentError,
    MissingInputError,
    StepAlreadyRegisteredError,
    StepsRegistry,
    TooManyArgumentsError,
    chain,
    get_step_json_schema,
    override,
    step,
)


@step
def push(items: list[str], item: str) -> list[str]:
    return [*items, item]


@step
def push_input(items: list[str], word: str = Input()) -> list[str]:
    return [*items, word]


@chain
def push_twice(item: str, *, sep: str = "") -> Flow[list[str]]:
    """Push an item twice."""
    return push(item) >> push(sep + item)


class TestChain:
    def test_builds_a_flat_flow(self) -> None:
        flow = push("a") >> push_twice("b") >> push("c")

        assert repr(flow) == "Flow(push >> push >> push >> push)"
        assert flow([]) == ["a", "b", "b", "c"]

    def test_keeps_metadata(self) -> None:
        assert push_twice.__name__ == "push_twice"
        assert push_twice.__doc__ == "Push an item twice."

    def test_chain_inside_chain(self) -> None:
        @chain
        def push_four(item: str) -> Flow[list[str]]:
            return push_twice(item) >> push_twice(item, sep="-")

        assert push_four("x")([]) == ["x", "x", "x", "-x"]

    def test_inputs_of_its_steps_are_checked_first(self) -> None:
        seen: list[str] = []

        @step
        def mark(items: list[str]) -> list[str]:
            seen.append("ran")
            return items

        @chain
        def with_input() -> Flow[list[str]]:
            return push_input()

        flow = mark() >> with_input()

        assert flow.inputs == {"word"}

        with pytest.raises(MissingInputError, match="'word' for step 'push_input'"):
            flow([])

        assert seen == []
        assert flow([], word="w") == ["w"]

    def test_argument_errors(self) -> None:
        with pytest.raises(MissingArgumentError, match="'item' for step 'push_twice'"):
            push_twice()  # type: ignore[call-arg]

        with pytest.raises(TooManyArgumentsError, match="for step 'push_twice'"):
            push_twice("a", "b")  # type: ignore[call-arg]

    def test_process(self) -> None:
        @chain
        def push_many(item: str, times: Annotated[int, Process(int)]) -> Flow[list[str]]:
            return Flow(*(action for _ in range(times) for action in push(item)))

        assert push_many("a", "3")([]) == ["a", "a", "a"]  # type: ignore[arg-type]

    def test_rejects_input(self) -> None:
        with pytest.raises(InvalidStepError, match="Chain 'bad' cannot take 'item' as Input"):

            @chain
            def bad(item: str = Input()) -> Flow[list[str]]:
                return push(item)

    def test_rejects_depends(self) -> None:
        with pytest.raises(InvalidStepError, match="Chain 'bad' cannot take 'item' as Depends"):

            @chain
            def bad(item: str = Depends(lambda: "x")) -> Flow[list[str]]:
                return push(item)

    def test_rejects_a_function_not_returning_a_flow(self) -> None:
        @chain
        def bad() -> Any:
            return push

        with pytest.raises(InvalidStepError, match="Chain 'bad' must return a Flow, got"):
            bad()

    def test_is_not_overridable(self) -> None:
        with pytest.raises(InvalidStepError, match="not a step factory"):
            override(push_twice)


class TestRegistryChain:
    @pytest.fixture
    def registry(self) -> StepsRegistry[list[str]]:
        registry = StepsRegistry[list[str]]()

        @registry.step()
        def add(items: list[str], item: str) -> list[str]:
            return [*items, item]

        @registry.chain(description="Add an item twice.")
        def add_twice(item: str, count: Annotated[int, Process(int)] = 2) -> Flow[list[str]]:
            return Flow(*(action for _ in range(count) for action in add(item)))

        @registry.chain(name="hidden_chain", hidden=True)
        def secret() -> Flow[list[str]]:
            return add("s")

        return registry

    def test_from_json(self, registry: StepsRegistry[list[str]]) -> None:
        flow = FlowCompiler(registry.steps).compile(
            [
                {"name": "add_twice", "args": ["a"]},
                {"name": "add_twice", "kwargs": {"item": "b", "count": "3"}},
            ],
        )

        assert repr(flow) == "Flow(add >> add >> add >> add >> add)"
        assert flow([]) == ["a", "a", "b", "b", "b"]

    def test_argument_error_has_json_path(self, registry: StepsRegistry[list[str]]) -> None:
        with pytest.raises(MissingArgumentError, match="for step 'add_twice'") as info:
            FlowCompiler(registry.steps).compile(
                [{"name": "add", "args": ["x"]}, {"name": "add_twice"}]
            )

        assert "at $[1]" in info.value.__notes__

    def test_schema(self, registry: StepsRegistry[list[str]]) -> None:
        schema = get_step_json_schema("add_twice", registry["add_twice"])

        assert schema["description"] == "Add an item twice."
        assert schema["properties"]["args"]["prefixItems"] == [
            {"type": "string"},
            {"type": "integer", "default": 2},
        ]

    def test_hidden_and_name(self, registry: StepsRegistry[list[str]]) -> None:
        assert list(registry.steps) == ["add", "add_twice"]
        assert "hidden_chain" not in registry

    def test_duplicate_name(self, registry: StepsRegistry[list[str]]) -> None:
        with pytest.raises(StepAlreadyRegisteredError):

            @registry.chain(name="add")
            def again() -> Flow[list[str]]:
                return Flow()
