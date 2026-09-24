"""Compile flow definitions (lists of step dictionaries, or JSON) into `Flow` objects."""

from collections.abc import Callable, Mapping, Sequence
from typing import Any, NotRequired, TypedDict

from .exceptions import InvalidFlowDefinitionError, PyflowstepError, StepDoesNotExistError
from .flow import Flow, compose

_STEP_DICT_SHAPE = '{"name": str, "args"?: list, "kwargs"?: dict[str, Any]}'


class StepDict(TypedDict):
    """The dictionary form of one step.

    Only `name` is required; `args` defaults to `[]` and `kwargs` to `{}`.

        {"name": "fill", "args": ["input[name=q]"], "kwargs": {"value": "pyflowstep"}}
    """

    name: str
    args: NotRequired[list[Any]]
    kwargs: NotRequired[dict[str, Any]]


type FlowDefinition = Sequence[StepDict]


class FlowCompiler[T]:
    """Compile a flow definition into a runnable `Flow`.

    A flow definition is a list of `StepDict` objects, one per step, run in
    order. Every problem is reported while compiling, before anything runs:
    malformed dictionaries, unknown step names, bad arguments and failing
    processors. Each error carries a note with its JSON path, e.g. `at $[2]`.

    The compiler works on already-parsed data (lists and dicts), so where the
    definition comes from (a JSON file, a database, an API) is up to you.

    Args:
        steps: A mapping from step name to step factory, typically
            `registry.steps`.

    Example:
    ```python
    >>> from pyflowstep import step
    >>> @step
    ... def add(total: int, amount: int) -> int:
    ...     return total + amount
    >>> @step
    ... def multiply(total: int, factor: int) -> int:
    ...     return total * factor
    >>> compiler = FlowCompiler[int]({"add": add, "multiply": multiply})
    >>> flow = compiler.compile([
    ...     {"name": "add", "args": [2]},
    ...     {"name": "multiply", "kwargs": {"factor": 10}},
    ... ])
    >>> flow
    Flow(add >> multiply)
    >>> flow(1)
    30

    ```

    """

    def __init__(self, steps: Mapping[str, Callable[..., Flow[T]]], /) -> None:
        self._steps = steps

    def compile(self, definition: FlowDefinition) -> Flow[T]:
        """Compile a list of step dictionaries into a single flat `Flow`."""
        if isinstance(definition, str | bytes | Mapping) or not isinstance(definition, Sequence):
            raise InvalidFlowDefinitionError(_invalid_definition_message(definition))

        return compose(
            *(self._compile_step(item, f"$[{index}]") for index, item in enumerate(definition)),
        )

    def _compile_step(self, item: Any, path: str) -> Flow[T]:
        try:
            step_dict = validate_step_dict(item, path)
            factory = self._find_step(step_dict["name"])
            return factory(*step_dict.get("args", []), **step_dict.get("kwargs", {}))
        except PyflowstepError as error:
            error.add_note(f"at {path}")
            raise

    def _find_step(self, name: str) -> Callable[..., Flow[T]]:
        if name not in self._steps:
            raise StepDoesNotExistError(name, self._steps.keys())
        return self._steps[name]


def validate_step_dict(item: Any, path: str = "$") -> StepDict:
    """Return `item` if it is a well-formed `StepDict`, raise otherwise.

    Raises:
        InvalidFlowDefinitionError: With a message explaining what is wrong at `path`.

    Example:
    ```python
    >>> validate_step_dict({"name": "click", "args": ["#go"]})
    {'name': 'click', 'args': ['#go']}
    >>> validate_step_dict({"name": "click", "selector": "#go"}, "$[0]")
    Traceback (most recent call last):
    ...
    pyflowstep.exceptions.InvalidFlowDefinitionError: Invalid step at $[0]: unknown keys ...

    ```

    """
    problem = _step_dict_problem(item)

    if problem is not None:
        msg = f"Invalid step at {path}: {problem}, expected {_STEP_DICT_SHAPE}, received {item!r}"
        raise InvalidFlowDefinitionError(msg)

    return item


def _step_dict_problem(item: Any) -> str | None:
    """Describe the first thing wrong with a step dictionary, or `None` if it is valid."""
    if not isinstance(item, Mapping):
        return "a step must be an object"

    if unknown_keys := item.keys() - frozenset({"name", "args", "kwargs"}):
        return f"unknown keys {sorted(map(str, unknown_keys))}"

    if not isinstance(item.get("name"), str):
        return "'name' is required and must be a string"

    if not isinstance(item.get("args", []), list):
        return "'args' must be a list"

    if not isinstance(item.get("kwargs", {}), Mapping):
        return "'kwargs' must be an object"

    if not all(isinstance(key, str) for key in item.get("kwargs", {})):
        return "'kwargs' keys must be strings"

    return None


def _invalid_definition_message(definition: Any) -> str:
    return (
        "Invalid flow definition at $: expected a list of steps like "
        f"[{_STEP_DICT_SHAPE}, ...], received {definition!r}"
    )
