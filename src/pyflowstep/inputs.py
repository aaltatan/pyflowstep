"""Run inputs: hand a flow the values only its caller has, when it runs.

A step parameter annotated with `Input[T]` is not an argument of the step:
nobody passes it while the flow is built, neither Python nor JSON. The caller
supplies it by name when it runs the flow:

    @step
    def fill_year(page: Page, selector: str, voucher: Input[Voucher]) -> Page: ...

    flow = fill_year("#year")      # only `selector` is an argument
    flow(page, voucher=voucher)    # `voucher` is supplied for this run

The name of the input is the name of the parameter. A flow checks the inputs
its steps require before the first step runs, so a forgotten one never fails
halfway through. A parameter with a default value is an optional input.

Use `Depends` when a provider can build the object, and `Input` when only the
caller of the flow has it.

Example:
```python
>>> from pyflowstep import step
>>> @step
... def add_tax(price: float, rate: Input[float]) -> float:
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
from typing import Annotated, Any

from .annotations import annotated_metadata, resolved_annotations
from .dependencies import Run
from .exceptions import InvalidInputError, MissingInputError

_UNSUPPORTED_KINDS = (Parameter.POSITIONAL_ONLY, Parameter.VAR_POSITIONAL, Parameter.VAR_KEYWORD)
_REQUIRED_INPUTS = "__pyflowstep_inputs__"


@dataclass(frozen=True, slots=True)
class RunInput:
    """The marker carried by `Input[T]`: "the caller of the flow supplies this parameter"."""


type Input[T] = Annotated[T, RunInput()]


def find_inputs(fn: Callable[..., Any]) -> dict[str, bool]:
    """Return the parameters of `fn` marked with `Input`, mapped to whether they are required.

    Example:
    ```python
    >>> def add_tax(price: float, label: str, rate: Input[float], bonus: Input[float] = 0.0): ...
    >>> find_inputs(add_tax)
    {'rate': True, 'bonus': False}

    ```

    """
    annotations = resolved_annotations(fn)
    return {
        name: parameter.default is Parameter.empty
        for name, parameter in signature(fn).parameters.items()
        if any(isinstance(item, RunInput) for item in annotated_metadata(annotations.get(name)))
    }


def step_inputs(fn: Callable[..., Any], step_name: str) -> dict[str, bool]:
    """Return the inputs of a step function after validating them.

    Raises:
        InvalidInputError: If the subject is marked, or an input sits on a
            positional-only, `*args` or `**kwargs` parameter.

    """
    inputs = find_inputs(fn)
    parameters = signature(fn).parameters
    subject = next(iter(parameters))

    if subject in inputs:
        msg = f"Step '{step_name}' cannot take its subject '{subject}' as a run input"
        raise InvalidInputError(msg)

    for name in inputs:
        if parameters[name].kind in _UNSUPPORTED_KINDS:
            msg = (
                f"Step '{step_name}' cannot take {parameters[name].kind.description} "
                f"parameter '{name}' as a run input"
            )
            raise InvalidInputError(msg)

    return inputs


def resolve_inputs(run: Run, inputs: Mapping[str, bool], step_name: str) -> dict[str, Any]:
    """Return the value of every input the run was given, optional ones only when present.

    Raises:
        MissingInputError: If the run was not given a required input.

    """
    missing = [name for name, required in inputs.items() if required and name not in run.inputs]

    if missing:
        raise MissingInputError(_missing_message((name, step_name) for name in missing))

    return {name: run.inputs[name] for name in inputs if name in run.inputs}


def mark_required_inputs(action: Callable[..., Any], inputs: Mapping[str, bool]) -> None:
    """Record on a step action the inputs it requires, for `required_inputs` to read."""
    required = frozenset(name for name, required in inputs.items() if required)
    setattr(action, _REQUIRED_INPUTS, required)


def required_inputs(action: Callable[..., Any]) -> frozenset[str]:
    """Return the names of the inputs an action requires; plain callables require none.

    Example:
    ```python
    >>> from pyflowstep import step
    >>> @step
    ... def add_tax(price: float, rate: Input[float], bonus: Input[float] = 0.0) -> float:
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
