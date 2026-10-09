"""Decorators that turn plain functions into step factories.

A *step function* takes the flow subject first, followed by its own arguments:

    def click(page: Page, selector: str) -> Page: ...

Decorating it produces a *step factory*: calling the factory with the
remaining arguments returns a single-step `Flow`, ready to be composed.

    click("button#submit")  # -> Flow(click)

Three markers can sit on a parameter:

- `Annotated[T, Process(fn)]` applies `fn` to the argument when the step is built,
  see `pyargprocessors`.
- `Depends(provider)` makes it no argument at all: it is injected when the flow
  runs, see `pyflowstep.dependencies`.
- `Input()` as the default makes it no argument either: the caller supplies it
  when it runs the flow, see `pyflowstep.inputs`.

Naming steps is a registry concern, see `StepsRegistry`.
"""

from collections.abc import Callable, Mapping
from functools import wraps
from inspect import BoundArguments, Parameter, Signature, signature
from typing import Any, Concatenate

from pyargprocessors import InvalidProcessorError, find_processors, process_arguments

from .dependencies import Dependency, resolve_dependencies, run_scope, step_dependencies
from .exceptions import InvalidStepError, to_argument_error
from .flow import Flow, action_name
from .inputs import RunInput, mark_required_inputs, resolve_inputs, step_inputs

type StepFn[T, **P] = Callable[Concatenate[T, P], T]
type TapFn[T, **P] = Callable[Concatenate[T, P], Any]
type StepFactory[T, **P] = Callable[P, Flow[T]]


def step[T, **P](fn: StepFn[T, P], /) -> StepFactory[T, P]:
    """Turn a `(subject, *args, **kwargs) -> subject` function into a step factory.

    Arguments are validated against the function signature as soon as the
    factory is called, so mistakes surface while *building* a flow, not
    halfway through running it.

    Raises:
        InvalidStepError: If `fn` does not accept the subject positionally.
        ArgumentError: A subclass is raised by the factory for bad arguments.
        pyargprocessors.ProcessArgumentError: Raised by the factory when a processor fails.

    Example:
    ```python
    >>> @step
    ... def add(total: int, amount: int) -> int:
    ...     return total + amount
    >>> @step
    ... def multiply(total: int, factor: int) -> int:
    ...     return total * factor
    >>> pipeline = add(2) >> multiply(10) >> add(amount=1)
    >>> pipeline
    Flow(add >> multiply >> add)
    >>> pipeline(1)
    31
    >>> add()
    Traceback (most recent call last):
    ...
    pyflowstep.exceptions.MissingArgumentError: missing a required argument: 'amount' for step 'add'

    ```

    """
    return _make_step(fn, passthrough=False)


def tap[T, **P](fn: TapFn[T, P], /) -> StepFactory[T, P]:
    """Like `step`, for side-effect functions: the return value is ignored.

    The subject passed in is handed, unchanged, to the next step. This removes
    the `return page` boilerplate from steps that act on a mutable object.

    Example:
    ```python
    >>> log: list[str] = []
    >>> @tap
    ... def record(value: int, label: str) -> None:
    ...     log.append(f"{label}={value}")
    >>> (record("before") >> Flow[int](lambda n: n * 10) >> record("after"))(4)
    40
    >>> log
    ['before=4', 'after=40']

    ```

    """
    return _make_step(fn, passthrough=True)


def bind_arguments(
    arguments_signature: Signature,
    step_name: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> BoundArguments:
    """Bind step arguments to a signature, raising the matching `ArgumentError`.

    Example:
    ```python
    >>> from inspect import signature
    >>> bind_arguments(signature(lambda selector: None), "click", ("#go",), {}).arguments
    {'selector': '#go'}
    >>> bind_arguments(signature(lambda selector: None), "click", (), {})
    Traceback (most recent call last):
    ...
    pyflowstep.exceptions.MissingArgumentError: missing a required argument: 'selector'...

    ```

    """
    try:
        return arguments_signature.bind(*args, **kwargs)
    except TypeError as error:
        raise to_argument_error(error, step_name) from error


def _make_step[T, **P](fn: TapFn[T, P], *, passthrough: bool) -> StepFactory[T, P]:
    step_name = action_name(fn)
    full_signature = _arguments_signature(fn, step_name)
    dependencies = step_dependencies(fn, step_name)
    inputs = step_inputs(fn, step_name)
    processors = find_processors(fn, name=step_name, skip=1)
    injected = dependencies.keys() | inputs.keys()

    if both := sorted(processors.keys() & injected):
        msg = (
            f"Step '{step_name}' cannot both process and inject {both}: nothing is passed for them"
        )
        raise InvalidProcessorError(msg)

    arguments_signature = Signature(
        [p for p in full_signature.parameters.values() if p.name not in injected],
    )

    @wraps(fn)
    def factory(*args: P.args, **kwargs: P.kwargs) -> Flow[T]:
        bound = bind_arguments(arguments_signature, step_name, args, kwargs)
        bound = process_arguments(processors, bound) if processors else bound
        call = (
            _inject(fn, step_name, full_signature, bound, dependencies=dependencies, inputs=inputs)
            if injected
            else _call(fn, bound)
        )
        action = _make_action(call, fn, step_name, passthrough=passthrough)
        mark_required_inputs(action, inputs)
        return Flow(action)

    factory.__signature__ = arguments_signature  # type: ignore[attr-defined]
    return factory


def _arguments_signature(fn: Callable[..., Any], step_name: str) -> Signature:
    """Return the signature of `fn` without its leading subject parameter."""
    try:
        subject, *parameters = signature(fn).parameters.values()
    except ValueError as error:
        msg = f"Step '{step_name}' must accept the flow subject as its first positional parameter"
        raise InvalidStepError(msg) from error

    if subject.kind not in (Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD):
        msg = (
            f"Step '{step_name}' must accept the flow subject as its first positional parameter, "
            f"got {subject.kind.description} parameter '{subject.name}'"
        )
        raise InvalidStepError(msg)

    return Signature(parameters)


def _call(fn: Callable[..., Any], bound: BoundArguments) -> Callable[[Any], Any]:
    """Return `subject -> fn(subject, <bound arguments>)`."""
    return lambda subject: fn(subject, *bound.args, **bound.kwargs)


def _inject(
    fn: Callable[..., Any],
    step_name: str,
    full_signature: Signature,
    bound: BoundArguments,
    *,
    dependencies: Mapping[str, Dependency],
    inputs: Mapping[str, RunInput],
) -> Callable[[Any], Any]:
    """Like `_call`, resolving the run inputs and the dependencies each time the step runs."""

    def call(subject: Any) -> Any:
        with run_scope() as run:
            resolved = {
                **resolve_inputs(run.inputs, inputs, step_name),
                **resolve_dependencies(run, dependencies),
            }
            arguments = BoundArguments(full_signature, {**bound.arguments, **resolved})  # type: ignore[arg-type]
            return fn(subject, *arguments.args, **arguments.kwargs)

    return call


def _make_action[T](
    call: Callable[[T], Any],
    fn: Callable[..., Any],
    step_name: str,
    *,
    passthrough: bool,
) -> Callable[[T], T]:
    def run(subject: T) -> T:
        result = call(subject)
        return subject if passthrough else result

    run.__name__ = run.__qualname__ = step_name
    run.__doc__ = fn.__doc__
    return run
