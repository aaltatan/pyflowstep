"""Dependency injection: hand steps the external objects JSON cannot describe.

A step parameter marked with `Depends(provider)` is not an argument of the
step: nobody passes it, neither Python nor JSON. Instead `provider` is called
to produce the object when the flow runs.

    def get_mailer() -> Mailer: ...

    @step
    def send_receipt(order: Order, template: str, mailer: Mailer = Depends(get_mailer)): ...

    send_receipt("receipt")  # only `template` is an argument

One flow run is one scope, like one request in a web framework: a provider is
called at most once per run and its object is shared by every step of that run.
A provider written as a generator is cleaned up when the run ends.

    def get_session() -> Iterator[Session]:
        session = Session()
        try:
            yield session
        finally:
            session.close()
"""

import sys
from collections.abc import Callable, Iterator, Mapping
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import cache
from inspect import Parameter, isgeneratorfunction, signature
from types import MappingProxyType
from typing import Any

from .annotations import annotated_metadata, resolved_annotations
from .exceptions import InvalidDependencyError

type Provider = Callable[..., Any]

_UNSUPPORTED_KINDS = (Parameter.POSITIONAL_ONLY, Parameter.VAR_POSITIONAL, Parameter.VAR_KEYWORD)


@dataclass(frozen=True, slots=True)
class Dependency:
    """The marker created by `Depends`: "call `provider` to get this parameter"."""

    provider: Provider


def Depends(provider: Provider, /) -> Any:  # noqa: N802
    """Mark a step (or provider) parameter as injected by calling `provider`.

    Use it as a default value, or inside `Annotated` to name a dependency once
    and reuse it:

        def send(order: Order, mailer: Mailer = Depends(get_mailer)) -> Order: ...

        type MailerDep = Annotated[Mailer, Depends(get_mailer)]
        def send(order: Order, mailer: MailerDep) -> Order: ...

    A provider is a function returning the object, or a generator function
    that yields it once and cleans up after the `yield`. Its own parameters may
    use `Depends` too.

    Example:
    ```python
    >>> from pyflowstep import step
    >>> def get_rate() -> float:
    ...     return 0.25
    >>> @step
    ... def add_tax(price: float, rate: float = Depends(get_rate)) -> float:
    ...     return price * (1 + rate)
    >>> add_tax()(100.0)
    125.0
    >>> add_tax(0.5)
    Traceback (most recent call last):
    ...
    pyflowstep.exceptions.TooManyArgumentsError: too many positional arguments for step 'add_tax'

    ```

    """
    if not callable(provider):
        msg = f"A dependency provider must be callable, got {provider!r}"
        raise InvalidDependencyError(msg)

    return Dependency(provider)


def find_dependencies(fn: Callable[..., Any]) -> dict[str, Dependency]:
    """Return the parameters of `fn` marked with `Depends`, by name.

    Example:
    ```python
    >>> def get_rate() -> float:
    ...     return 0.25
    >>> from typing import Annotated
    >>> type Rate = Annotated[float, Depends(get_rate)]
    >>> def add_tax(price: float, label: str, rate: Rate, extra: float = Depends(get_rate)): ...
    >>> list(find_dependencies(add_tax))
    ['rate', 'extra']

    ```

    """
    try:
        parameters = signature(fn).parameters
    except ValueError:  # builtins without a signature take no dependencies
        return {}

    annotations = resolved_annotations(fn)
    markers = (
        (name, _marker(parameter, annotations.get(name))) for name, parameter in parameters.items()
    )
    return {name: marker for name, marker in markers if marker is not None}


def step_dependencies(fn: Callable[..., Any], step_name: str) -> dict[str, Dependency]:
    """Return the dependencies of a step function after validating them.

    Raises:
        InvalidDependencyError: If the subject is marked, a dependency sits on a
            positional-only, `*args` or `**kwargs` parameter, or a provider is
            circular or has a required parameter that is not a dependency.

    """
    dependencies = find_dependencies(fn)
    parameters = signature(fn).parameters
    subject = next(iter(parameters))

    if subject in dependencies:
        msg = f"Step '{step_name}' cannot inject its subject '{subject}'"
        raise InvalidDependencyError(msg)

    for name, dependency in dependencies.items():
        if parameters[name].kind in _UNSUPPORTED_KINDS:
            msg = (
                f"Step '{step_name}' cannot inject {parameters[name].kind.description} "
                f"parameter '{name}'"
            )
            raise InvalidDependencyError(msg)
        _validate_provider(dependency.provider, ())

    return dependencies


@dataclass(slots=True)
class Run:
    """The scope of one flow run: resolved objects and their pending cleanups."""

    cache: dict[Provider, Any] = field(default_factory=dict)
    cleanups: ExitStack = field(default_factory=ExitStack)


_RUN: ContextVar[Run | None] = ContextVar("pyflowstep_run", default=None)
_OVERRIDES: ContextVar[Mapping[Provider, Provider]] = ContextVar(
    "pyflowstep_overrides",
    default=MappingProxyType({}),
)


@contextmanager
def run_scope() -> Iterator[Run]:
    """Open the scope of a flow run, or join the one already open.

    When the outermost scope closes, generator providers are cleaned up in
    reverse order. An error raised inside the scope is thrown into them at
    their `yield`, and is always re-raised: a provider cannot swallow it.
    """
    active = _RUN.get()

    if active is not None:
        yield active
        return

    run = Run()
    token = _RUN.set(run)

    try:
        yield run
    except BaseException:
        run.cleanups.__exit__(*sys.exc_info())
        raise
    else:
        run.cleanups.close()
    finally:
        _RUN.reset(token)


def resolve_dependencies(run: Run, dependencies: Mapping[str, Dependency]) -> dict[str, Any]:
    """Return the object of every dependency, calling each provider once per run."""
    return {name: _resolve(run, dependency.provider) for name, dependency in dependencies.items()}


@contextmanager
def override_dependencies(overrides: Mapping[Provider, Provider]) -> Iterator[None]:
    """Replace providers inside a `with` block, typically to use fakes in tests.

    Keys are the original providers, values the providers to call instead.
    Nested blocks add to the outer ones, and everything is restored on exit.

    Example:
    ```python
    >>> from pyflowstep import step
    >>> def get_rate() -> float:
    ...     return 0.25
    >>> @step
    ... def add_tax(price: float, rate: float = Depends(get_rate)) -> float:
    ...     return price * (1 + rate)
    >>> with override_dependencies({get_rate: lambda: 0.5}):
    ...     add_tax()(100.0)
    150.0
    >>> add_tax()(100.0)
    125.0

    ```

    """
    token = _OVERRIDES.set(MappingProxyType({**_OVERRIDES.get(), **overrides}))

    try:
        yield
    finally:
        _OVERRIDES.reset(token)


def _resolve(run: Run, provider: Provider) -> Any:
    if provider in run.cache:
        return run.cache[provider]

    actual = _OVERRIDES.get().get(provider, provider)
    arguments = resolve_dependencies(run, _provider_dependencies(actual))

    if isgeneratorfunction(actual):
        value = run.cleanups.enter_context(contextmanager(actual)(**arguments))
    else:
        value = actual(**arguments)

    run.cache[provider] = value
    return value


@cache
def _provider_dependencies(provider: Provider) -> Mapping[str, Dependency]:
    return MappingProxyType(find_dependencies(provider))


def _marker(parameter: Parameter, annotation: Any) -> Dependency | None:
    if isinstance(parameter.default, Dependency):
        return parameter.default

    return next(
        (item for item in annotated_metadata(annotation) if isinstance(item, Dependency)),
        None,
    )


def _validate_provider(provider: Provider, path: tuple[Provider, ...]) -> None:
    if provider in path:
        chain = " -> ".join(_name(item) for item in (*path, provider))
        msg = f"Circular dependency: {chain}"
        raise InvalidDependencyError(msg)

    try:
        parameters = signature(provider).parameters
    except ValueError:  # builtins without a signature are called with no arguments
        return

    dependencies = find_dependencies(provider)

    for name, parameter in parameters.items():
        if name in dependencies and parameter.kind in _UNSUPPORTED_KINDS:
            msg = (
                f"Provider '{_name(provider)}' cannot inject {parameter.kind.description} "
                f"parameter '{name}'"
            )
            raise InvalidDependencyError(msg)

        if name in dependencies:
            _validate_provider(dependencies[name].provider, (*path, provider))
        elif _is_required(parameter):
            msg = (
                f"Provider '{_name(provider)}' has a required parameter '{name}' that is not a "
                "dependency; mark it with Depends(...) or give it a default"
            )
            raise InvalidDependencyError(msg)


def _is_required(parameter: Parameter) -> bool:
    is_variadic = parameter.kind in (Parameter.VAR_POSITIONAL, Parameter.VAR_KEYWORD)
    return parameter.default is Parameter.empty and not is_variadic


def _name(provider: Provider) -> str:
    return getattr(provider, "__name__", None) or repr(provider)
