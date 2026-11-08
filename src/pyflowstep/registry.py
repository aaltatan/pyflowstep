"""A registry that collects named steps for one subject type."""

from collections.abc import Callable, Iterator, Mapping
from functools import wraps
from types import MappingProxyType
from typing import Any

from pyvocabulary import Vocabulary

from .exceptions import StepAlreadyRegisteredError, StepDoesNotExistError
from .steps import StepFactory, StepFn, TapFn, override, step, tap
from .validators import _invalid_step_name, validate_step_name


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
        self._steps: Vocabulary[StepFactory[T, ...]] = Vocabulary(
            "step",
            does_not_exist=StepDoesNotExistError,
            already_registered=StepAlreadyRegisteredError,
            invalid_name=_invalid_step_name,
        )

    @property
    def steps(self) -> Mapping[str, StepFactory[T, ...]]:
        """A read-only mapping of every visible step, by name."""
        return MappingProxyType(dict(self._steps))

    def __getitem__(self, name: str) -> StepFactory[T, ...]:
        return self._steps[name]

    def __contains__(self, name: object) -> bool:
        return name in self._steps

    def __iter__(self) -> Iterator[str]:
        return iter(self._steps)

    def __len__(self) -> int:
        return len(self._steps)

    def step[**P](
        self,
        *,
        name: str | None = None,
        description: str | None = None,
        hidden: bool = False,
    ) -> Callable[[StepFn[T, P]], StepFactory[T, P]]:
        """Return a decorator registering a `(subject, ...) -> subject` step function.

        Args:
            name: The step name; defaults to the function name.
            description: Overrides the function docstring (shown in the JSON schema).
            hidden: Keep the step out of the registry lookups (`steps`, `[]`, `in`),
                hence out of the compiler and the JSON schema. The returned
                factory stays fully usable from Python.

        """

        def decorator(fn: StepFn[T, P]) -> StepFactory[T, P]:
            return self.register(
                fn,
                name=name,
                description=description,
                hidden=hidden,
            )

        return decorator

    def tap[**P](
        self,
        *,
        name: str | None = None,
        description: str | None = None,
        hidden: bool = False,
    ) -> Callable[[TapFn[T, P]], StepFactory[T, P]]:
        """Return a decorator registering a side-effect step whose return value is ignored.

        See `pyflowstep.tap`.

        Args:
            name: The step name; defaults to the function name.
            description: Overrides the function docstring (shown in the JSON schema).
            hidden: Keep the step out of the registry lookups (`steps`, `[]`, `in`),
                hence out of the compiler and the JSON schema. The returned
                factory stays fully usable from Python.

        """

        def decorator(fn: TapFn[T, P]) -> StepFactory[T, P]:
            return self.register(
                fn,
                name=name,
                description=description,
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
        hidden: bool = False,
        passthrough: bool = False,
    ) -> StepFactory[T, P]:
        """Register `fn` as a step without decorator syntax and return its factory.

        Useful for registering functions you do not own, or lambdas (with `name`).
        The registered name is also the name shown in `repr` and error messages.

        Args:
            fn: The step function; its first positional parameter receives the subject.
            name: The step name; defaults to the function name.
            description: Overrides the function docstring (shown in the JSON schema).
            hidden: Keep the step out of the registry lookups (`steps`, `[]`, `in`),
                hence out of the compiler and the JSON schema. The returned
                factory stays fully usable from Python.
            passthrough: Ignore the return value of `fn` and pass the subject on
                unchanged, like `tap`.

        Raises:
            StepAlreadyRegisteredError: If the name is already taken.
            InvalidStepNameError: If the name is not a valid Python identifier.
            InvalidStepError: If `fn` does not accept the subject positionally.

        """
        return self._add(
            fn,
            tap if passthrough else step,
            name=name,
            description=description,
            hidden=hidden,
        )

    def override[**P](
        self,
        original: StepFactory[T, ...],
        /,
        *,
        name: str | None = None,
        description: str | None = None,
        hidden: bool = False,
    ) -> Callable[[TapFn[T, P]], StepFactory[T, P]]:
        """Return a decorator registering a variant of a step, see `pyflowstep.override`.

        Args:
            original: The step factory whose body the variant runs.
            name: The step name; defaults to the stub name.
            description: Overrides the docstring of the stub, or of `original`
                when the stub has none (shown in the JSON schema).
            hidden: Keep the step out of the registry lookups (`steps`, `[]`, `in`),
                hence out of the compiler and the JSON schema. The returned
                factory stays fully usable from Python.

        Example:
        ```python
        >>> from pyflowstep import Input
        >>> registry = StepsRegistry[int]()
        >>> @registry.step()
        ... def add(total: int, amount: int) -> int:
        ...     return total + amount
        >>> @registry.override(registry["add"], name="add_input")
        ... def add_from_run(total: int, amount: int = Input()) -> int: ...
        >>> registry["add_input"]()(1, amount=2)
        3

        ```

        """
        make = override(original)

        def decorator(fn: TapFn[T, P]) -> StepFactory[T, P]:
            return self._add(fn, make, name=name, description=description, hidden=hidden)

        return decorator

    def _add[F: Callable[..., Any], **P](
        self,
        fn: F,
        make: Callable[[F], StepFactory[T, P]],
        *,
        name: str | None,
        description: str | None,
        hidden: bool,
    ) -> StepFactory[T, P]:
        """Validate the name, build the factory with `make` under that name, and add it."""
        step_name = validate_step_name(name or getattr(fn, "__name__", ""))

        if self._steps.is_registered(step_name):
            raise StepAlreadyRegisteredError(step_name)

        factory = make(_renamed(fn, step_name))
        factory.__doc__ = description or factory.__doc__
        self._steps.add(step_name, factory, hidden=hidden)

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
