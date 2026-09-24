import pytest

from pyflowstep import Flow, compose
from pyflowstep.flow import action_name


def increment(n: int) -> int:
    return n + 1


def double(n: int) -> int:
    return n * 2


def explode(_: int) -> int:
    msg = "boom"
    raise RuntimeError(msg)


class TestFlowCall:
    def test_runs_actions_in_order(self) -> None:
        assert Flow(increment, double)(3) == 8
        assert Flow(double, increment)(3) == 7

    def test_empty_flow_is_identity(self) -> None:
        subject = object()
        assert Flow()(subject) is subject

    def test_flow_can_be_reused(self) -> None:
        flow = Flow(increment)
        assert [flow(n) for n in range(3)] == [1, 2, 3]

    def test_each_action_receives_previous_result(self) -> None:
        seen: list[int] = []

        def spy(n: int) -> int:
            seen.append(n)
            return n

        Flow(spy, increment, spy, double, spy)(1)
        assert seen == [1, 2, 4]

    def test_nested_flows_are_callable_actions(self) -> None:
        assert Flow(Flow(increment, increment), double)(0) == 4


class TestFlowComposition:
    def test_rshift_concatenates_flows(self) -> None:
        flow = Flow(increment) >> Flow(double, increment)
        assert flow.actions == (increment, double, increment)
        assert flow(1) == 5

    def test_rshift_accepts_plain_callables(self) -> None:
        flow = Flow(increment) >> double
        assert flow.actions == (increment, double)

    def test_rrshift_lets_plain_callables_lead(self) -> None:
        flow = double >> Flow(increment)
        assert isinstance(flow, Flow)
        assert flow.actions == (double, increment)
        assert flow(5) == 11

    def test_rshift_never_mutates_operands(self) -> None:
        left, right = Flow(increment), Flow(double)
        combined = left >> right
        assert left.actions == (increment,)
        assert right.actions == (double,)
        assert combined is not left

    def test_rshift_is_associative(self) -> None:
        a, b, c = Flow(increment), Flow(double), Flow(increment)
        assert ((a >> b) >> c).actions == (a >> (b >> c)).actions

    @pytest.mark.parametrize("other", [1, "text", None])
    def test_rshift_rejects_non_callables(self, other: object) -> None:
        with pytest.raises(TypeError):
            Flow(increment) >> other  # type: ignore[operator]

    @pytest.mark.parametrize("other", [1, "text", None])
    def test_rrshift_rejects_non_callables(self, other: object) -> None:
        with pytest.raises(TypeError):
            other >> Flow(increment)  # type: ignore[operator]


class TestCompose:
    def test_composes_left_to_right(self) -> None:
        assert compose(increment, double)(1) == 4

    def test_flattens_flows(self) -> None:
        flow = compose(Flow(increment, double), increment, Flow(double))
        assert flow.actions == (increment, double, increment, double)

    def test_without_actions_returns_identity(self) -> None:
        flow = compose()
        assert isinstance(flow, Flow)
        assert len(flow) == 0
        assert flow(42) == 42

    def test_mixes_with_rshift(self) -> None:
        flow = compose(increment) >> double >> compose(increment)
        assert flow(0) == 3


class TestFlowProtocol:
    def test_len_and_iter(self) -> None:
        flow = Flow(increment, double)
        assert len(flow) == 2
        assert list(flow) == [increment, double]

    def test_empty_flow_is_truthy(self) -> None:
        assert Flow()

    def test_repr_lists_step_names(self) -> None:
        assert repr(Flow(increment, double)) == "Flow(increment >> double)"
        assert repr(Flow()) == "Flow()"

    def test_repr_of_nested_flow(self) -> None:
        assert repr(Flow(Flow(increment), double)) == "Flow(Flow(increment) >> double)"


class TestActionName:
    def test_uses_dunder_name(self) -> None:
        assert action_name(increment) == "increment"

    def test_falls_back_to_repr(self) -> None:
        class Callable:
            def __call__(self, n: int) -> int:
                return n

            def __repr__(self) -> str:
                return "<custom>"

        assert action_name(Callable()) == "<custom>"


class TestErrorNotes:
    def test_exception_propagates_unchanged_with_a_note(self) -> None:
        with pytest.raises(RuntimeError, match="boom"):
            Flow(increment, explode, double)(1)

    def test_nested_flows_add_one_note_per_level(self) -> None:
        with pytest.raises(RuntimeError):
            Flow(increment, Flow(double, explode))(1)

    def test_actions_after_the_failure_do_not_run(self) -> None:
        calls: list[str] = []

        def record(n: int) -> int:
            calls.append("ran")
            return n

        with pytest.raises(RuntimeError):
            Flow(explode, record)(1)

        assert calls == []
