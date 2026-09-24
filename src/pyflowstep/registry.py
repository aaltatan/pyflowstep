"""A registry that collects named steps for one subject type."""

from collections.abc import Callable, Iterator, Mapping
from functools import wraps
from inspect import signature
from types import EllipsisType, MappingProxyType
from typing import Any

from .exceptions import StepAlreadyRegisteredError, StepDoesNotExistError
from .flow import Flow
from .processors import process_arguments, processor_lookup
from .steps import StepFactory, StepFn, TapFn, bind_arguments, step, tap
from .validators import validate_step_name


class StepsRegistry[T]:
    """Collect named steps for subjects of type `T`.

    A registry is the vocabulary of a flow language: its visible steps are what
    a `FlowCompiler` understands and what `get_flow_json_schema` describes.
    Hidden steps stay usable from Python but are invisible to both.

    Example:
    ```python
    >>> from pyflowstep import FlowCompiler
    >>> registry = StepsRegistry[list[str]]()
    >>> @registry.step()
    ... def push(stack: list[str], item: str) -> list[str]:
    ...     '''Push an item on top of the stack.'''
    ...     return [*stack, item]
    >>> @registry.step(name="pop")
    ... def pop_item(stack: list[str]) -> list[str]:
    ...     return stack[:-1]
    >>> sorted(registry.steps)
    ['pop', 'push']
    >>> (registry["push"]("a") >> registry["push"]("b") >> registry["pop"]())([])
    ['a']
    >>> FlowCompiler(registry.steps).compile([{"name": "push", "args": ["x"]}])([])
    ['x']

    ```

    """

    def __init__(self) -> None:
        self._steps: dict[str, StepFactory[T, ...]] = {}
        self._hidden: set[str] = set()

    @property
    def steps(self) -> Mapping[str, StepFactory[T, ...]]:
        """A read-only mapping of every visible step, by name."""
        return MappingProxyType(
            {name: factory for name, factory in self._steps.items() if name not in self._hidden},
        )

    def __getitem__(self, name: str) -> StepFactory[T, ...]:
        if name not in self.steps:
            raise StepDoesNotExistError(name, self.steps.keys())
        return self._steps[name]

    def __contains__(self, name: object) -> bool:
        return name in self.steps

    def __iter__(self) -> Iterator[str]:
        return iter(self.steps)

    def __len__(self) -> int:
        return len(self.steps)

    def step[**P](
        self,
        *,
        name: str | None = None,
        description: str | None = None,
        processors: (
            Callable[[Any], Any] | Mapping[str | EllipsisType, Callable[[Any], Any]] | None
        ) = None,
        hidden: bool = False,
    ) -> Callable[[StepFn[T, P]], StepFactory[T, P]]:
        """Return a decorator registering a `(subject, ...) -> subject` step function.

        Args:
            name: The step name; defaults to the function name.
            description: Overrides the function docstring (shown in the JSON schema).
            processors (`((Any) -> Any) | Mapping[str | EllipsisType, (Any) -> Any] | None`):
                How to transform arguments before the step is built: a callable for
                every argument, or a mapping of parameter names to callables where
                the key `...` covers the remaining arguments. `None` leaves them as-is.
            hidden: Keep the step out of the registry lookups (`steps`, `[]`, `in`),
                hence out of the compiler and the JSON schema. The returned
                factory stays fully usable from Python.

        """

        def decorator(fn: StepFn[T, P]) -> StepFactory[T, P]:
            return self.register(
                fn,
                name=name,
                description=description,
                processors=processors,
                hidden=hidden,
            )

        return decorator

    def tap[**P](
        self,
        *,
        name: str | None = None,
        description: str | None = None,
        processors: (
            Callable[[Any], Any] | Mapping[str | EllipsisType, Callable[[Any], Any]] | None
        ) = None,
        hidden: bool = False,
    ) -> Callable[[TapFn[T, P]], StepFactory[T, P]]:
        """Return a decorator registering a side-effect step whose return value is ignored.

        See `pyflowstep.tap`.

        Args:
            name: The step name; defaults to the function name.
            description: Overrides the function docstring (shown in the JSON schema).
            processors (`((Any) -> Any) | Mapping[str | EllipsisType, (Any) -> Any] | None`):
                How to transform arguments before the step is built: a callable for
                every argument, or a mapping of parameter names to callables where
                the key `...` covers the remaining arguments. `None` leaves them as-is.
            hidden: Keep the step out of the registry lookups (`steps`, `[]`, `in`),
                hence out of the compiler and the JSON schema. The returned
                factory stays fully usable from Python.

        """

        def decorator(fn: TapFn[T, P]) -> StepFactory[T, P]:
            return self.register(
                fn,
                name=name,
                description=description,
                processors=processors,
                hidden=hidden,
                passthrough=True,
            )

        return decorator

    def register[**P](
        self,
        fn: TapFn[T, P],
        /,
        *,
        name: str | None = None,
        description: str | None = None,
        processors: (
            Callable[[Any], Any] | Mapping[str | EllipsisType, Callable[[Any], Any]] | None
        ) = None,
        hidden: bool = False,
        passthrough: bool = False,
    ) -> StepFactory[T, P]:
        """Register `fn` as a step without decorator syntax and return its factory.

        Useful for registering functions you do not own, or lambdas (with `name`).
        The registered name is also the name shown in `repr` and error messages,
        and processors run on every call of the returned factory, before the
        arguments are bound to the step.

        Args:
            fn: The step function; its first positional parameter receives the subject.
            name: The step name; defaults to the function name.
            description: Overrides the function docstring (shown in the JSON schema).
            processors (`((Any) -> Any) | Mapping[str | EllipsisType, (Any) -> Any] | None`):
                How to transform arguments before the step is built: a callable for
                every argument, or a mapping of parameter names to callables where
                the key `...` covers the remaining arguments. `None` leaves them as-is.
            hidden: Keep the step out of the registry lookups (`steps`, `[]`, `in`),
                hence out of the compiler and the JSON schema. The returned
                factory stays fully usable from Python.
            passthrough: Ignore the return value of `fn` and pass the subject on
                unchanged, like `tap`.

        Raises:
            StepAlreadyRegisteredError: If the name is already taken.
            InvalidStepNameError: If the name is not a valid Python identifier.
            InvalidStepError: If `fn` does not accept the subject positionally.
            InvalidProcessorsError: If `processors` is malformed or names an unknown
                parameter.

        """
        step_name = validate_step_name(name or getattr(fn, "__name__", ""))

        if step_name in self._steps:
            raise StepAlreadyRegisteredError(step_name)

        make = tap if passthrough else step
        factory = _with_processors(make(_renamed(fn, step_name)), processors)
        factory.__doc__ = description or fn.__doc__

        self._steps[step_name] = factory
        if hidden:
            self._hidden.add(step_name)

        return factory


def _renamed[F: Callable[..., Any]](fn: F, name: str) -> F:
    """Return `fn` itself, or a thin wrapper exposing it under `name`."""
    if getattr(fn, "__name__", None) == name:
        return fn

    @wraps(fn)
    def renamed(*args: Any, **kwargs: Any) -> Any:
        return fn(*args, **kwargs)

    renamed.__name__ = renamed.__qualname__ = name
    return renamed  # type: ignore[return-value]


def _with_processors[T, **P](
    factory: StepFactory[T, P],
    processors: Callable[[Any], Any] | Mapping[str | EllipsisType, Callable[[Any], Any]] | None,
) -> StepFactory[T, P]:
    """Return a factory that processes its arguments before calling `factory`."""
    if processors is None:
        return factory

    arguments_signature = signature(factory)
    lookup = processor_lookup(processors, arguments_signature.parameters, factory.__name__)

    @wraps(factory)
    def processed(*args: P.args, **kwargs: P.kwargs) -> Flow[T]:
        bound = bind_arguments(arguments_signature, factory.__name__, args, kwargs)
        arguments = process_arguments(lookup, bound)
        return factory(*arguments.args, **arguments.kwargs)

    return processed
