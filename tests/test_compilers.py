import json
from typing import Annotated, Any

import pytest

from pyflowstep import (
    Depends,
    Flow,
    FlowCompiler,
    InvalidFlowDefinitionError,
    MissingArgumentError,
    Parse,
    ParseArgumentError,
    PyflowstepError,
    StepDoesNotExistError,
    StepsRegistry,
    TooManyArgumentsError,
    UnexpectedKeywordArgumentError,
    validate_step_dict,
)

calculator = StepsRegistry[float]()


@calculator.step()
def add(total: float, amount: float) -> float:
    return total + amount


@calculator.step()
def multiply(total: float, factor: float = 2) -> float:
    return total * factor


@calculator.step()
def round_to(total: float, *, places: Annotated[int, Parse(int)]) -> float:
    return round(total, places)


@calculator.step()
def divide(total: float, by: float) -> float:
    return total / by


@calculator.step(hidden=True)
def reset(_: float) -> float:
    return 0


@pytest.fixture
def compiler() -> FlowCompiler[float]:
    return FlowCompiler(calculator.steps)


class TestCompile:
    def test_compiles_steps_in_order(self, compiler: FlowCompiler[float]) -> None:
        flow = compiler.compile(
            [
                {"name": "add", "args": [1]},
                {"name": "multiply", "kwargs": {"factor": 10}},
                {"name": "add", "args": [], "kwargs": {"amount": 0.5}},
            ],
        )
        assert flow(1) == 20.5

    def test_result_is_a_flat_flow(self, compiler: FlowCompiler[float]) -> None:
        flow = compiler.compile([{"name": "add", "args": [1]}, {"name": "multiply"}])
        assert isinstance(flow, Flow)
        assert len(flow) == 2
        assert repr(flow) == "Flow(add >> multiply)"

    def test_args_and_kwargs_are_optional(self, compiler: FlowCompiler[float]) -> None:
        assert compiler.compile([{"name": "multiply"}])(4) == 8

    def test_empty_definition_is_identity(self, compiler: FlowCompiler[float]) -> None:
        flow = compiler.compile([])
        assert len(flow) == 0
        assert flow(3) == 3

    def test_accepts_tuples_of_steps(self, compiler: FlowCompiler[float]) -> None:
        assert compiler.compile(({"name": "add", "args": [1]},))(1) == 2

    def test_parsers_run_at_compile_time(self, compiler: FlowCompiler[float]) -> None:
        flow = compiler.compile([{"name": "round_to", "kwargs": {"places": "1"}}])
        assert flow(3.14159) == 3.1

    def test_compiled_flow_composes_with_python_steps(self, compiler: FlowCompiler[float]) -> None:
        flow = compiler.compile([{"name": "add", "args": [1]}]) >> multiply(3)
        assert flow(1) == 6

    def test_definition_is_not_mutated(self, compiler: FlowCompiler[float]) -> None:
        definition = [{"name": "add", "args": [1], "kwargs": {}}]
        snapshot = json.dumps(definition)
        compiler.compile(definition)  # type: ignore[arg-type]
        assert json.dumps(definition) == snapshot

    def test_compiler_works_with_any_mapping(self) -> None:
        compiler = FlowCompiler[float]({"double": multiply})
        assert compiler.compile([{"name": "double"}])(2) == 4

    def test_runtime_errors_keep_their_type(self, compiler: FlowCompiler[float]) -> None:
        flow = compiler.compile([{"name": "add", "args": [1]}, {"name": "divide", "args": [0]}])

        with pytest.raises(ZeroDivisionError):
            flow(1)


class TestParsedJson:
    """Parsing JSON is the caller's job; the compiler takes the parsed data."""

    def test_compiles_the_output_of_json_loads(self, compiler: FlowCompiler[float]) -> None:
        flow = compiler.compile(json.loads('[{"name": "add", "args": [2]}, {"name": "multiply"}]'))
        assert flow(1) == 6

    @pytest.mark.parametrize("text", ['{"name": "add"}', '"add"', "42", "null"])
    def test_json_that_is_not_a_list(self, compiler: FlowCompiler[float], text: str) -> None:
        with pytest.raises(InvalidFlowDefinitionError, match=r"Invalid flow definition at \$"):
            compiler.compile(json.loads(text))


class TestInvalidDefinitions:
    @pytest.mark.parametrize("definition", [{"name": "add"}, "add", b"add", 42, None])
    def test_definition_must_be_a_list(
        self,
        compiler: FlowCompiler[float],
        definition: Any,
    ) -> None:
        with pytest.raises(InvalidFlowDefinitionError, match="expected a list of steps"):
            compiler.compile(definition)

    @pytest.mark.parametrize(
        ("item", "problem"),
        [
            ("add", "a step must be an object"),
            (["add"], "a step must be an object"),
            (None, "a step must be an object"),
            ({}, "'name' is required"),
            ({"args": [1]}, "'name' is required"),
            ({"name": 1}, "'name' is required and must be a string"),
            ({"name": "add", "arguments": [1]}, "unknown keys \\['arguments'\\]"),
            ({"name": "add", "args": 1}, "'args' must be a list"),
            ({"name": "add", "args": {"amount": 1}}, "'args' must be a list"),
            ({"name": "add", "kwargs": [1]}, "'kwargs' must be an object"),
            ({"name": "add", "kwargs": {1: 1}}, "'kwargs' keys must be strings"),
        ],
    )
    def test_malformed_step(self, compiler: FlowCompiler[float], item: Any, problem: str) -> None:
        with pytest.raises(InvalidFlowDefinitionError, match=problem) as info:
            compiler.compile([{"name": "add", "args": [1]}, item])

        assert "Invalid step at $[1]" in str(info.value)
        assert info.value.__notes__ == ["at $[1]"]

    def test_unknown_step(self, compiler: FlowCompiler[float]) -> None:
        with pytest.raises(StepDoesNotExistError, match="'subtract' does not exist") as info:
            compiler.compile([{"name": "add", "args": [1]}, {"name": "subtract", "args": [1]}])

        assert info.value.__notes__ == ["at $[1]"]
        assert "Available steps: add, divide, multiply, round_to" in str(info.value)

    def test_hidden_steps_are_not_compilable(self, compiler: FlowCompiler[float]) -> None:
        with pytest.raises(StepDoesNotExistError, match="'reset'"):
            compiler.compile([{"name": "reset"}])

    def test_empty_compiler(self) -> None:
        with pytest.raises(StepDoesNotExistError, match=r"Available steps: \(none\)"):
            FlowCompiler[float]({}).compile([{"name": "add"}])

    @pytest.mark.parametrize(
        ("item", "error"),
        [
            ({"name": "add"}, MissingArgumentError),
            ({"name": "add", "args": [1, 2]}, TooManyArgumentsError),
            ({"name": "add", "args": [1], "kwargs": {"extra": 1}}, UnexpectedKeywordArgumentError),
            ({"name": "round_to", "args": [2]}, TooManyArgumentsError),
            ({"name": "round_to", "kwargs": {"places": "two"}}, ParseArgumentError),
        ],
    )
    def test_argument_errors_have_the_path(
        self,
        compiler: FlowCompiler[float],
        item: Any,
        error: type[PyflowstepError],
    ) -> None:
        with pytest.raises(error) as info:
            compiler.compile([{"name": "multiply"}, {"name": "multiply"}, item])

        assert info.value.__notes__ == ["at $[2]"]

    def test_first_error_wins(self, compiler: FlowCompiler[float]) -> None:
        with pytest.raises(StepDoesNotExistError) as info:
            compiler.compile([{"name": "nope"}, {"bad": True}])
        assert info.value.__notes__ == ["at $[0]"]

    def test_all_compile_errors_share_a_base_class(self, compiler: FlowCompiler[float]) -> None:
        for definition in ([{"name": "nope"}], [{"name": "add"}], "x", [{}]):
            with pytest.raises(PyflowstepError):
                compiler.compile(definition)  # type: ignore[arg-type]


class TestValidateStepDict:
    def test_returns_the_same_object(self) -> None:
        item = {"name": "add", "args": [1], "kwargs": {}}
        assert validate_step_dict(item) is item

    def test_default_path(self) -> None:
        with pytest.raises(InvalidFlowDefinitionError, match="Invalid step at \\$:"):
            validate_step_dict({})

    def test_message_shows_the_expected_shape_and_the_input(self) -> None:
        with pytest.raises(InvalidFlowDefinitionError) as info:
            validate_step_dict({"nme": "add"}, "$[3]")

        message = str(info.value)
        assert '"name": str' in message
        assert "{'nme': 'add'}" in message

    def test_invalid_definition_is_a_value_error(self) -> None:
        with pytest.raises(ValueError, match="a step must be an object"):
            validate_step_dict([])


class TestDependencies:
    """Dependencies are resolved when the compiled flow runs, never taken from JSON."""

    @pytest.fixture
    def setup(self) -> tuple[FlowCompiler[list[str]], list[int]]:
        registry = StepsRegistry[list[str]]()
        calls: list[int] = []

        def get_stamp() -> str:
            calls.append(1)
            return f"run-{len(calls)}"

        @registry.step()
        def mark(items: list[str], label: str, stamp: str = Depends(get_stamp)) -> list[str]:
            return [*items, f"{label}@{stamp}"]

        return FlowCompiler(registry.steps), calls

    def test_compiled_flow_shares_one_object_per_run(
        self,
        setup: tuple[FlowCompiler[list[str]], list[int]],
    ) -> None:
        compiler, calls = setup
        flow = compiler.compile([{"name": "mark", "args": ["a"]}, {"name": "mark", "args": ["b"]}])

        assert calls == []  # compiling calls no provider
        assert flow([]) == ["a@run-1", "b@run-1"]
        assert flow([]) == ["a@run-2", "b@run-2"]

    @pytest.mark.parametrize(
        ("item", "error"),
        [
            ({"name": "mark", "args": ["a", "mine"]}, TooManyArgumentsError),
            (
                {"name": "mark", "args": ["a"], "kwargs": {"stamp": "mine"}},
                UnexpectedKeywordArgumentError,
            ),
        ],
    )
    def test_json_cannot_pass_a_dependency(
        self,
        setup: tuple[FlowCompiler[list[str]], list[int]],
        item: Any,
        error: type[PyflowstepError],
    ) -> None:
        compiler, _ = setup

        with pytest.raises(error) as info:
            compiler.compile([item])

        assert info.value.__notes__ == ["at $[0]"]
