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
from dataclasses import dataclass
from functools import wraps
from inspect import BoundArguments, Parameter, Signature, signature
from typing import Any, Concatenate

from pyargprocessors import InvalidProcessorError, find_processors, process_arguments

from .dependencies import (
    Dependency,
    find_dependencies,
    resolve_dependencies,
    run_scope,
    step_dependencies,
)
from .exceptions import InvalidStepError, to_argument_error
from .flow import Flow, action_name
from .inputs import (
    RunInput,
    find_inputs,
    mark_inputs,
    mark_output,
    resolve_inputs,
    step_inputs,
    validate_output_name,
)

type StepFn[T, **P] = Callable[Concatenate[T, P], T]
type TapFn[T, **P] = Callable[Concatenate[T, P], Any]
type StepFactory[T, **P] = Callable[P, Flow[T]]

_ORIGIN = "__pyflowstep_origin__"


@dataclass(frozen=True, slots=True)
class _Origin:
    """What a step factory runs, recorded so `override` can reuse it."""

    body: Callable[..., Any]
    passthrough: bool
    output: str | None


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


def output[T, **P](name: str, /) -> Callable[[TapFn[T, P]], StepFactory[T, P]]:
    """Return a decorator for steps whose return value becomes the run input `name`.

    The subject passes through unchanged, like `tap`. Later steps of the run
    read the value with an ordinary `name: <type> = Input()`, so they stay
    reusable. A flow checks the order before its first step runs: a step that
    reads `name` before it is produced still needs it from the caller.

    A later output of the same name replaces the earlier one, and a produced
    value replaces one the caller passed, for the steps after the producer.
    A nested flow called with inputs of its own keeps its outputs to itself.

    Raises:
        InvalidInputError: If `name` is not a valid identifier, or is a keyword.

    Example:
    ```python
    >>> from pyflowstep import Input, step
    >>> @output("count")
    ... def count(items: list[str]) -> int:
    ...     return len(items)
    >>> @step
    ... def label(items: list[str], count: int = Input()) -> list[str]:
    ...     return [f"{item}/{count}" for item in items]
    >>> flow = count() >> label()
    >>> flow.inputs
    frozenset()
    >>> flow(["a", "b"])
    ['a/2', 'b/2']

    ```

    """
    output_name = validate_output_name(name)

    def decorator(fn: TapFn[T, P]) -> StepFactory[T, P]:
        return _make_step(fn, passthrough=True, output=output_name)

    return decorator


def override[T, **P](
    original: StepFactory[T, ...],
    /,
) -> Callable[[TapFn[T, P]], StepFactory[T, P]]:
    """Make a variant of a step: same body and parameters, other defaults.

    The decorated function is a stub whose body never runs; the body of
    `original` does. The stub gives the variant its name, its arguments and
    their markers: a parameter can become `Input()`, `Depends(...)` or get
    another plain default. Whether the step is a `step`, a `tap` or an
    `output` carries over from `original`. The docstring is the stub's, or the
    original's when the stub has none.

    A stub is used because a type checker cannot express "the same parameters
    with one default changed" from `original` alone.

    Raises:
        InvalidStepError: If `original` is not a step factory, the parameters after
            the subject differ in name, order or kind, or a parameter that is
            processed on `original` is neither processed nor injected on the stub.

    Example:
    ```python
    >>> from pyflowstep import Input, step
    >>> @step
    ... def add(total: int, amount: int) -> int:
    ...     return total + amount
    >>> @override(add)
    ... def add_input(total: int, amount: int = Input()) -> int: ...
    >>> add_input()(1, amount=2)
    3

    ```

    """
    origin: _Origin | None = getattr(original, _ORIGIN, None)

    if origin is None:
        msg = (
            f"'{action_name(original)}' is not a step factory; override takes a factory made "
            "by step, tap, output or a StepsRegistry"
        )
        raise InvalidStepError(msg)

    def decorator(stub: TapFn[T, P]) -> StepFactory[T, P]:
        _check_override(original, stub)
        factory = _make_step(
            stub,
            passthrough=origin.passthrough,
            body=origin.body,
            output=origin.output,
        )
        factory.__doc__ = stub.__doc__ or original.__doc__

        return factory

    return decorator


def chain[T, **P](fn: Callable[P, Flow[T]], /) -> StepFactory[T, P]:
    """Turn a function that builds a flow from other steps into a step factory.

    Every parameter of `fn` is a build argument; there is no subject. The
    factory binds and processes its arguments like a step factory does, so
    mistakes raise the same `ArgumentError`s, and the flow `fn` returns stays
    flat: the `Input`s of its steps are inputs of any flow it joins.

    Raises:
        InvalidStepError: If a parameter of `fn` is `Input()` or `Depends(...)` (declare
            them on the steps instead), or, from the factory, if `fn` returns
            something other than a `Flow`.

    Example:
    ```python
    >>> from pyflowstep import step
    >>> @step
    ... def add(total: int, amount: int) -> int:
    ...     return total + amount
    >>> @chain
    ... def add_twice(amount: int) -> Flow[int]:
    ...     return add(amount) >> add(amount)
    >>> flow = add_twice(2) >> add(1)
    >>> flow
    Flow(add >> add >> add)
    >>> flow(0)
    5

    ```

    """
    chain_name = action_name(fn)

    for name, marker in [*find_inputs(fn).items(), *find_dependencies(fn).items()]:
        kind = "Input" if isinstance(marker, RunInput) else "Depends"
        msg = (
            f"Chain '{chain_name}' cannot take '{name}' as {kind}; a chain has no run of its own, "
            "declare it on the steps the chain returns"
        )
        raise InvalidStepError(msg)

    arguments_signature = signature(fn)
    processors = find_processors(fn, name=chain_name)

    @wraps(fn)
    def factory(*args: P.args, **kwargs: P.kwargs) -> Flow[T]:
        bound = bind_arguments(arguments_signature, chain_name, args, kwargs)
        bound = process_arguments(processors, bound) if processors else bound
        flow = fn(*bound.args, **bound.kwargs)

        if not isinstance(flow, Flow):
            msg = f"Chain '{chain_name}' must return a Flow, got {flow!r}"
            raise InvalidStepError(msg)

        return flow

    return factory


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


def _make_step[T, **P](
    fn: TapFn[T, P],
    *,
    passthrough: bool,
    body: Callable[..., Any] | None = None,
    output: str | None = None,
) -> StepFactory[T, P]:
    """Return the factory of a step whose signature data comes from `fn` and runs `body or fn`."""
    run = body or fn
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
        # `run` may be another function (override): hand it every value, never its own defaults
        bound.apply_defaults()
        call = (
            _inject(run, step_name, full_signature, bound, dependencies=dependencies, inputs=inputs)
            if injected
            else _call(run, bound)
        )
        action = _make_action(call, fn, step_name, passthrough=passthrough, output=output)
        mark_inputs(action, inputs)
        mark_output(action, output)

        return Flow(action)

    factory.__signature__ = arguments_signature  # type: ignore[attr-defined]
    setattr(factory, _ORIGIN, _Origin(run, passthrough, output))

    return factory


def _check_override(original: Callable[..., Any], stub: Callable[..., Any]) -> None:
    """Raise if `stub` cannot stand in for the signature of `original`, see `override`."""
    stub_name = action_name(stub)
    original_name = action_name(original)
    spec = original.__wrapped__  # type: ignore[attr-defined]  # the function its signature came from
    expected = _arguments_signature(spec, original_name).parameters.values()
    given = _arguments_signature(stub, stub_name).parameters.values()

    if [(p.name, p.kind) for p in expected] != [(p.name, p.kind) for p in given]:
        msg = (
            f"Override '{stub_name}' must keep the parameters of '{original_name}' after the "
            f"subject, with the same names, order and kinds: expected {_describe(expected)}, "
            f"got {_describe(given)}"
        )
        raise InvalidStepError(msg)

    processed = find_processors(spec, name=original_name, skip=1).keys()
    kept = find_processors(stub, name=stub_name, skip=1).keys()
    injected = find_dependencies(stub).keys() | find_inputs(stub).keys()

    if lost := sorted(processed - kept - injected):
        names = ", ".join(f"'{name}'" for name in lost)
        msg = (
            f"Override '{stub_name}' drops the Process of {names} from '{original_name}'; "
            "repeat the Annotated[..., Process(...)] on the stub, or inject the parameter"
        )
        raise InvalidStepError(msg)


def _describe(parameters: Any) -> str:
    return "(" + ", ".join(f"{p.name}: {p.kind.description}" for p in parameters) + ")"


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
    output: str | None = None,
) -> Callable[[T], T]:
    def run(subject: T) -> T:
        result = call(subject)

        if output is not None:
            with run_scope() as scope:
                scope.inputs[output] = result

        return subject if passthrough else result

    run.__name__ = run.__qualname__ = step_name
    run.__doc__ = fn.__doc__
    return run
