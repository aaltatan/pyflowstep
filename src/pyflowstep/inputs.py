"""Run inputs: hand a flow the values only its caller has, when it runs.

A step parameter whose default is `Input()` is not an argument of the step:
nobody passes it while the flow is built, neither Python nor JSON. The caller
supplies it by name when it runs the flow:

    @step
    def fill_year(page: Page, selector: str, voucher: Voucher = Input()) -> Page: ...

    flow = fill_year("#year")      # only `selector` is an argument
    flow(page, voucher=voucher)    # `voucher` is supplied for this run

The name of the input is the name of the parameter. A flow checks the inputs
its steps require before the first step runs, so a forgotten one never fails
halfway through. `Input(default=...)` makes the input optional.

Use `Depends` when a provider can build the object, and `Input` when only the
caller of the flow has it.

Example:
```python
>>> from pyflowstep import step
>>> @step
... def add_tax(price: float, rate: float = Input()) -> float:
...     return price * (1 + rate)
>>> add_tax()(100.0, rate=0.25)
125.0
>>> add_tax()(100.0)
Traceback (most recent call last):
...
pyflowstep.exceptions.MissingInputError: missing run input 'rate' for step 'add_tax'...

```

"""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from inspect import Parameter, signature
from typing import Any

from pyargprocessors import annotated_metadata, resolved_annotations

from .exceptions import InvalidInputError, MissingInputError

_REQUIRED_INPUTS = "__pyflowstep_inputs__"


class _Required:
    """The default of an input that has none: the caller must supply it."""

    def __repr__(self) -> str:
        return "<required>"


_REQUIRED: Any = _Required()


@dataclass(frozen=True, slots=True)
class RunInput:
    """The marker created by `Input`: "the caller of the flow supplies this parameter"."""

    default: Any = _REQUIRED

    @property
    def required(self) -> bool:
        """Whether the caller must supply the input."""
        return self.default is _REQUIRED


def Input(*, default: Any = _REQUIRED) -> Any:  # noqa: N802
    """Mark a step parameter as supplied by the caller when the flow runs.

    Use it as the default value of the parameter. The parameter stops being an
    argument of the step; `flow(subject, name=value)` fills it for one run.

    Args:
        default: The value used when the caller supplies none, which makes the
            input optional. Without it the input is required.

    Example:
    ```python
    >>> from pyflowstep import step
    >>> @step
    ... def greet(names: list, user: str = Input(), mark: str = Input(default="!")) -> list:
    ...     return [*names, user + mark]
    >>> greet()([], user="Ada")
    ['Ada!']
    >>> greet()([], user="Ada", mark="?")
    ['Ada?']
    >>> sorted(greet().inputs)
    ['user']

    ```

    """
    return RunInput(default)


def find_inputs(fn: Callable[..., Any]) -> dict[str, RunInput]:
    """Return the parameters of `fn` whose default is `Input()`, by name.

    Example:
    ```python
    >>> def add_tax(price: float, rate: float = Input(), bonus: float = Input(default=0.0)): ...
    >>> {name: marker.required for name, marker in find_inputs(add_tax).items()}
    {'rate': True, 'bonus': False}

    ```

    """
    return {
        name: parameter.default
        for name, parameter in signature(fn).parameters.items()
        if isinstance(parameter.default, RunInput)
    }


def step_inputs(fn: Callable[..., Any], step_name: str) -> dict[str, RunInput]:
    """Return the inputs of a step function after validating them.

    Raises:
        InvalidInputError: If the subject or a positional-only parameter is
            marked, or `Input()` is used inside `Annotated` instead of as a default.

    """
    inputs = find_inputs(fn)
    parameters = signature(fn).parameters
    annotations = resolved_annotations(fn)
    subject = next(iter(parameters))

    for name in parameters:
        if any(isinstance(item, RunInput) for item in annotated_metadata(annotations.get(name))):
            msg = (
                f"Step '{step_name}' uses Input inside Annotated for '{name}'; write it as the "
                f"default value, `{name}: <type> = Input()`, so type checkers see the parameter "
                "as optional"
            )
            raise InvalidInputError(msg)

    if subject in inputs:
        msg = f"Step '{step_name}' cannot take its subject '{subject}' as a run input"
        raise InvalidInputError(msg)

    for name in inputs:
        if parameters[name].kind is Parameter.POSITIONAL_ONLY:
            msg = (
                f"Step '{step_name}' cannot take positional-only parameter '{name}' as a run input"
            )
            raise InvalidInputError(msg)

    return inputs


def resolve_inputs(
    given: Mapping[str, Any],
    inputs: Mapping[str, RunInput],
    step_name: str,
) -> dict[str, Any]:
    """Return the value of every input: the one `given`, or the default of an optional input.

    Raises:
        MissingInputError: If a required input was not given.

    """
    missing = [name for name, marker in inputs.items() if marker.required and name not in given]

    if missing:
        raise MissingInputError(_missing_message((name, step_name) for name in missing))

    return {name: given.get(name, marker.default) for name, marker in inputs.items()}


def mark_required_inputs(action: Callable[..., Any], inputs: Mapping[str, RunInput]) -> None:
    """Record on a step action the inputs it requires, for `required_inputs` to read."""
    required = frozenset(name for name, marker in inputs.items() if marker.required)
    setattr(action, _REQUIRED_INPUTS, required)


def required_inputs(action: Callable[..., Any]) -> frozenset[str]:
    """Return the names of the inputs an action requires; plain callables require none.

    Example:
    ```python
    >>> from pyflowstep import step
    >>> @step
    ... def add_tax(price: float, rate: float = Input(), bonus: float = Input(default=0.0)):
    ...     return price * (1 + rate) + bonus
    >>> required_inputs(add_tax().actions[0])
    frozenset({'rate'})
    >>> required_inputs(abs)
    frozenset()

    ```

    """
    return getattr(action, _REQUIRED_INPUTS, frozenset())


def check_inputs(actions: Iterable[Callable[..., Any]], given: Mapping[str, Any]) -> None:
    """Raise if `given` lacks an input one of `actions` requires.

    Raises:
        MissingInputError: Naming every missing input and the step that needs it.

    """
    missing = [
        (name, getattr(action, "__name__", repr(action)))
        for action in actions
        for name in sorted(required_inputs(action) - given.keys())
    ]

    if missing:
        raise MissingInputError(_missing_message(missing))


def _missing_message(missing: Iterable[tuple[str, str]]) -> str:
    steps_by_input: dict[str, list[str]] = {}

    for name, step_name in missing:
        steps = steps_by_input.setdefault(name, [])
        if step_name not in steps:
            steps.append(step_name)

    details = ", ".join(
        f"'{name}' for step{'s' if len(steps) > 1 else ''} {', '.join(map(repr, steps))}"
        for name, steps in steps_by_input.items()
    )
    names = ", ".join(f"{name}=..." for name in steps_by_input)
    plural = "s" if len(steps_by_input) > 1 else ""

    return f"missing run input{plural} {details}; run the flow as flow(subject, {names})"
