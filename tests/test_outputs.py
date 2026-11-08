import pytest

from pyflowstep import (
    Depends,
    Flow,
    FlowCompiler,
    Input,
    InvalidInputError,
    MissingInputError,
    StepsRegistry,
    chain,
    output,
    override,
    step,
)


@output("number")
def read_number(items: list[str]) -> str:
    return f"n{len(items)}"


@step
def write(items: list[str], number: str = Input()) -> list[str]:
    return [*items, number]


@step
def write_optional(items: list[str], number: str = Input(default="none")) -> list[str]:
    return [*items, number]


@step
def push(items: list[str], item: str) -> list[str]:
    return [*items, item]


class TestOutput:
    def test_value_reaches_input_and_subject_passes_through(self) -> None:
        assert (read_number() >> write())(["a"]) == ["a", "n1"]

    def test_produced_names_are_not_flow_inputs(self) -> None:
        assert (read_number() >> write()).inputs == frozenset()
        assert (write() >> read_number()).inputs == {"number"}

    def test_reading_before_producing_fails_before_any_step(self) -> None:
        seen: list[str] = []

        @output("number")
        def spy(items: list[str]) -> str:
            seen.append("ran")
            return "x"

        with pytest.raises(MissingInputError, match="'number' for step 'write'"):
            (write() >> spy())([])

        assert seen == []

    def test_optional_reader_takes_the_produced_value(self) -> None:
        assert (write_optional() >> read_number() >> write_optional())([]) == ["none", "n1"]

    def test_later_output_replaces_earlier(self) -> None:
        flow = read_number() >> write() >> push("b") >> read_number() >> write()

        assert flow([]) == ["n0", "b", "n2"]

    def test_produced_value_replaces_the_callers_after_the_producer(self) -> None:
        assert (write() >> read_number() >> write())([], number="given") == ["given", "n1"]

    def test_step_needing_its_own_output_needs_it_from_the_caller(self) -> None:
        @output("number")
        def bump(items: list[str], number: str = Input()) -> str:
            return number + "!"

        flow = bump() >> write()

        assert flow.inputs == {"number"}
        assert flow([], number="1") == ["1!"]

    def test_no_leak_between_runs(self) -> None:
        flow = read_number() >> write()
        flow(["a"])

        with pytest.raises(MissingInputError):
            write()([])

    def test_nested_flow_with_its_own_inputs_keeps_its_outputs(self) -> None:
        inner = read_number() >> write()

        @step
        def run_inner(items: list[str]) -> list[str]:
            return inner(items, other="x")

        flow = read_number() >> push("b") >> run_inner() >> write()

        assert flow([]) == ["b", "n1", "n0"]

    def test_signature_leaves_out_produced_names(self) -> None:
        @(read_number() >> write()).signature
        def typed(items: list[str], /) -> list[str]: ...

        assert typed([]) == ["n0"]

        with pytest.raises(InvalidInputError, match="unknown input 'number'"):

            @(read_number() >> write()).signature
            def wrong(items: list[str], /, *, number: str) -> list[str]: ...

    def test_through_a_chain(self) -> None:
        @chain
        def number_it() -> Flow[list[str]]:
            return read_number() >> write()

        flow = push("a") >> number_it()

        assert flow.inputs == frozenset()
        assert flow([]) == ["a", "n1"]

    def test_with_own_input_and_dependency(self) -> None:
        @output("label")
        def make_label(
            items: list[str], prefix: str = Input(), sep: str = Depends(lambda: ":")
        ) -> str:
            return f"{prefix}{sep}{len(items)}"

        @step
        def show(items: list[str], label: str = Input()) -> list[str]:
            return [*items, label]

        assert (make_label() >> show())(["a"], prefix="p") == ["a", "p:1"]

    def test_producer_returning_none(self) -> None:
        @output("number")
        def nothing(items: list[str]) -> None:
            return None

        @step
        def show(items: list[str], number: object = Input()) -> list[str]:
            return [*items, repr(number)]

        assert (nothing() >> show())([]) == ["None"]

    def test_override_keeps_output(self) -> None:
        @output("count")
        def count(items: list[str], offset: int) -> int:
            return len(items) + offset

        @override(count)
        def count_from_input(items: list[str], offset: int = Input()) -> int: ...

        @step
        def show(items: list[str], count: int = Input()) -> list[str]:
            return [*items, str(count)]

        assert (count_from_input() >> show())(["a"], offset=10) == ["a", "11"]

    @pytest.mark.parametrize("name", ["", "1x", "a-b", "class", "None"])
    def test_invalid_names(self, name: str) -> None:
        with pytest.raises(InvalidInputError, match="Invalid output name"):
            output(name)


class TestRegistryOutput:
    def test_from_json(self) -> None:
        registry = StepsRegistry[list[str]]()

        @registry.output("number", step_name="read", description="Read the number.")
        def read_it(items: list[str]) -> str:
            return f"n{len(items)}"

        registry.register(write.__wrapped__, name="write")  # type: ignore[attr-defined]

        flow = FlowCompiler(registry.steps).compile([{"name": "read"}, {"name": "write"}])

        assert repr(flow) == "Flow(read >> write)"
        assert flow.inputs == frozenset()
        assert flow([]) == ["n0"]
        assert read_it.__doc__ == "Read the number."

    def test_hidden(self) -> None:
        registry = StepsRegistry[list[str]]()

        @registry.output("number", hidden=True)
        def read_it(items: list[str]) -> str:
            return "x"

        assert "read_it" not in registry
        assert (read_it() >> write())([]) == ["x"]
