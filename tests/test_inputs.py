from inspect import signature
from typing import Annotated

import pytest
from pyargprocessors import InvalidProcessorError, Process

from pyflowstep import (
    Depends,
    Flow,
    FlowCompiler,
    Input,
    InvalidDependencyError,
    InvalidInputError,
    MissingInputError,
    StepsRegistry,
    TooManyArgumentsError,
    UnexpectedKeywordArgumentError,
    get_step_json_schema,
    step,
    tap,
)
from pyflowstep.inputs import RunInput, find_inputs, required_inputs


@step
def prefixed(items: list[str], item: str, prefix: str = Input()) -> list[str]:
    return [*items, prefix + item]


@step
def suffixed(items: list[str], item: str, suffix: str = Input(default="")) -> list[str]:
    return [*items, item + suffix]


class TestDeclaration:
    def test_input_returns_a_marker(self) -> None:
        assert Input() == RunInput()
        assert Input().required
        assert not Input(default=None).required
        assert Input(default=None).default is None
        assert repr(Input()) == "RunInput(default=<required>)"

    def test_find_inputs_tells_required_from_optional(self) -> None:
        def fn(
            subject: int, plain: str, rate: float = Input(), bonus: float = Input(default=0.0)
        ) -> int: ...

        inputs = find_inputs(fn)

        assert list(inputs) == ["rate", "bonus"]
        assert inputs["rate"].required
        assert not inputs["bonus"].required

    def test_string_annotations(self) -> None:
        @step
        def use(items: "list[str]", prefix: "str" = Input()) -> "list[str]":
            return [*items, prefix]

        assert use()([], prefix=">") == [">"]

    def test_input_between_ordinary_parameters(self) -> None:
        @step
        def use(items: list[str], first: str, prefix: str = Input(), last: str = "!") -> list[str]:
            return [*items, prefix + first + last]

        assert use("a")([], prefix=">") == [">a!"]
        assert use("a", "?")([], prefix=">") == [">a?"]
        assert use("a", last="?")([], prefix=">") == [">a?"]

    def test_keyword_only_input_before_a_required_argument(self) -> None:
        @step
        def use(items: list[str], *, prefix: str = Input(), item: str) -> list[str]:
            return [*items, prefix + item]

        assert use(item="a")([], prefix=">") == [">a"]

    def test_tap_with_input(self) -> None:
        seen: list[str] = []

        @tap
        def record(items: list[str], prefix: str = Input()) -> None:
            seen.append(prefix)

        assert record()(["a"], prefix=">") == ["a"]
        assert seen == [">"]

    def test_input_next_to_a_dependency(self) -> None:
        @step
        def use(
            items: list[str], prefix: str = Input(), mark: str = Depends(lambda: "!")
        ) -> list[str]:
            return [*items, prefix + mark]

        assert use()([], prefix=">") == [">!"]


class TestInvisibleArguments:
    def test_factory_signature_hides_inputs(self) -> None:
        assert list(signature(prefixed).parameters) == ["item"]
        assert list(signature(suffixed).parameters) == ["item"]

    def test_cannot_be_passed_positionally(self) -> None:
        with pytest.raises(TooManyArgumentsError):
            prefixed("a", ">")

    def test_cannot_be_passed_by_keyword(self) -> None:
        with pytest.raises(UnexpectedKeywordArgumentError):
            prefixed("a", prefix=">")

    def test_json_schema_hides_inputs(self) -> None:
        schema = get_step_json_schema("prefixed", prefixed)

        assert list(schema["properties"]["kwargs"]["properties"]) == ["item"]
        assert len(schema["properties"]["args"]["prefixItems"]) == 1


class TestRunning:
    def test_every_step_receives_the_input(self) -> None:
        flow = prefixed("a") >> prefixed("b")

        assert flow([], prefix=">") == [">a", ">b"]

    def test_each_run_has_its_own_inputs(self) -> None:
        flow = prefixed("a")

        assert flow([], prefix=">") == [">a"]
        assert flow([], prefix="#") == ["#a"]

    def test_optional_input_falls_back_to_its_default(self) -> None:
        assert suffixed("a")([]) == ["a"]
        assert suffixed("a")([], suffix="!") == ["a!"]

    def test_optional_input_may_default_to_none(self) -> None:
        @step
        def use(items: list[str], mark: str | None = Input(default=None)) -> list[str]:
            return [*items, repr(mark)]

        assert use()([]) == ["None"]
        assert use().inputs == frozenset()

    def test_extra_inputs_are_ignored(self) -> None:
        assert prefixed("a")([], prefix=">", unused=1) == [">a"]
        assert Flow[int](abs)(-1, unused=1) == 1

    def test_an_input_may_be_named_like_the_subject_parameter(self) -> None:
        @step
        def use(items: list[str], obj: str = Input()) -> list[str]:
            return [*items, obj]

        assert use()([], obj="x") == ["x"]

    def test_flow_lists_its_required_inputs(self) -> None:
        flow = prefixed("a") >> suffixed("b") >> Flow(list)

        assert flow.inputs == frozenset({"prefix"})
        assert Flow[int](abs).inputs == frozenset()
        assert required_inputs(prefixed("a").actions[0]) == frozenset({"prefix"})

    def test_inputs_survive_composition(self) -> None:
        flow = Flow(list) >> (prefixed("a") >> prefixed("b"))

        assert flow.inputs == frozenset({"prefix"})
        assert flow((), prefix=">") == [">a", ">b"]


class TestMissingInputs:
    def test_missing_input_fails_before_any_step_runs(self) -> None:
        ran: list[str] = []

        @tap
        def record(items: list[str]) -> None:
            ran.append("record")

        flow = record() >> prefixed("a")

        with pytest.raises(
            MissingInputError, match="missing run input 'prefix' for step 'prefixed'"
        ):
            flow([])

        assert ran == []

    def test_message_names_every_input_and_step(self) -> None:
        @step
        def named(items: list[str], prefix: str = Input(), name: str = Input()) -> list[str]:
            return [*items, prefix + name]

        flow = prefixed("a") >> named()

        with pytest.raises(MissingInputError) as error:
            flow([])

        message = str(error.value)
        assert "missing run inputs" in message
        assert "'prefix' for steps 'prefixed', 'named'" in message
        assert "'name' for step 'named'" in message
        assert "flow(subject, prefix=..., name=...)" in message

    def test_message_names_a_repeated_step_once(self) -> None:
        with pytest.raises(MissingInputError) as error:
            (prefixed("a") >> prefixed("b"))([])

        assert str(error.value).startswith("missing run input 'prefix' for step 'prefixed';")

    def test_running_an_action_directly_without_its_input(self) -> None:
        (action,) = prefixed("a").actions

        with pytest.raises(MissingInputError, match="'prefix' for step 'prefixed'"):
            action([])

    def test_missing_input_is_a_type_error(self) -> None:
        with pytest.raises(TypeError):
            prefixed("a")([])


class TestNestedFlows:
    def test_flow_called_inside_a_step_sees_the_outer_inputs(self) -> None:
        @step
        def twice(items: list[str], inner: Flow[list[str]]) -> list[str]:
            return inner(inner(items))

        assert twice(prefixed("a"))([], prefix=">") == [">a", ">a"]

    def test_inner_inputs_overlay_the_outer_ones_for_that_call_only(self) -> None:
        @step
        def shouted(items: list[str], inner: Flow[list[str]]) -> list[str]:
            return inner(items, prefix="!")

        flow = prefixed("a") >> shouted(prefixed("b") >> suffixed("c")) >> prefixed("d")

        assert flow([], prefix=">", suffix="?") == [">a", "!b", "c?", ">d"]

    def test_nested_run_shares_the_dependencies_of_the_outer_run(self) -> None:
        calls: list[int] = []

        def provider() -> int:
            calls.append(1)
            return len(calls)

        @step
        def use(items: list[int], obj: int = Depends(provider)) -> list[int]:
            return [*items, obj]

        @step
        def nested(items: list[int], inner: Flow[list[int]]) -> list[int]:
            return inner(items, extra=1)

        assert (use() >> nested(use()))([]) == [1, 1]

    def test_missing_input_of_a_nested_flow_surfaces_when_it_is_reached(self) -> None:
        @step
        def nested(items: list[str], inner: Flow[list[str]]) -> list[str]:
            return inner(items)

        with pytest.raises(MissingInputError, match="'prefix' for step 'prefixed'"):
            nested(prefixed("a"))([])

    def test_scope_is_reset_after_a_run(self) -> None:
        flow = prefixed("a")
        flow([], prefix=">")

        with pytest.raises(MissingInputError):
            flow([])


class TestCompiledFlows:
    def test_json_flow_receives_inputs_and_cannot_set_them(self) -> None:
        registry = StepsRegistry[list[str]]()

        @registry.step()
        def push(items: list[str], item: str, prefix: str = Input()) -> list[str]:
            return [*items, prefix + item]

        compiler = FlowCompiler(registry.steps)
        flow = compiler.compile(
            [{"name": "push", "args": ["a"]}, {"name": "push", "kwargs": {"item": "b"}}]
        )

        assert flow.inputs == frozenset({"prefix"})
        assert flow([], prefix=">") == [">a", ">b"]

        with pytest.raises(UnexpectedKeywordArgumentError):
            compiler.compile([{"name": "push", "kwargs": {"item": "a", "prefix": ">"}}])


class TestInvalidDeclarations:
    def test_subject_cannot_be_an_input(self) -> None:
        def fn(items: list[str] = Input()) -> list[str]: ...

        with pytest.raises(InvalidInputError, match="subject 'items'"):
            step(fn)

    def test_positional_only_parameter_cannot_be_an_input(self) -> None:
        def fn(items: list[str], prefix: str = Input(), /) -> list[str]: ...

        with pytest.raises(InvalidInputError, match="positional-only parameter 'prefix'"):
            step(fn)

    def test_input_inside_annotated_is_rejected(self) -> None:
        def fn(items: list[str], prefix: Annotated[str, Input()]) -> list[str]: ...

        with pytest.raises(InvalidInputError, match=r"`prefix: <type> = Input\(\)`"):
            step(fn)

    def test_parameter_cannot_be_both_processed_and_an_input(self) -> None:
        def fn(
            items: list[str], prefix: Annotated[str, Process(str.strip)] = Input()
        ) -> list[str]: ...

        with pytest.raises(InvalidProcessorError, match="cannot both process and inject"):
            step(fn)

    def test_provider_cannot_take_an_input(self) -> None:
        def provider(prefix: str = Input()) -> str: ...

        def fn(items: list[str], obj: str = Depends(provider)) -> list[str]: ...

        with pytest.raises(InvalidDependencyError, match="cannot take the run input 'prefix'"):
            step(fn)
