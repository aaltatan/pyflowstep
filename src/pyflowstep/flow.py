"""The `Flow` type: an immutable, composable pipeline of `T -> T` actions."""

from collections.abc import Callable, Iterator
from functools import reduce, wraps
from typing import Any, Concatenate

from .dependencies import run_scope
from .inputs import check_inputs, check_signature, required_inputs

type Action[T] = Callable[[T], T]


class Flow[T]:
    """An immutable sequence of actions applied, in order, to a single subject.

    A flow is a callable `T -> T`. Calling it threads the subject through every
    action: the output of one action is the input of the next. Flows compose
    with `>>`, which always returns a *new* flow and never mutates its operands.

    Keyword arguments given to the call are the run inputs: `flow(page, user=user)`
    hands `user` to every step that declares `user: User = Input()`.

    Args:
        *actions: The callables to run, in order. Each one takes the subject and
            returns the (possibly new) subject. With no actions the flow is the
            identity.

    Example:
    ```python
    >>> increment = Flow[int](lambda n: n + 1)
    >>> double = Flow[int](lambda n: n * 2)
    >>> pipeline = increment >> double >> increment
    >>> pipeline(3)
    9
    >>> len(pipeline)
    3
    >>> Flow[int]()(7)  # an empty flow is the identity
    7

    ```

    """

    __slots__ = ("_actions",)

    def __init__(self, *actions: Action[T]) -> None:
        self._actions = actions

    @property
    def actions(self) -> tuple[Action[T], ...]:
        """The actions of the flow, in execution order."""
        return self._actions

    @property
    def inputs(self) -> frozenset[str]:
        """The names of the run inputs the steps of the flow require, see `Input`."""
        return frozenset().union(*map(required_inputs, self._actions))

    def __call__(self, obj: T, /, **inputs: Any) -> T:
        with run_scope(inputs) as run:
            check_inputs(self._actions, run.inputs)
            return reduce(lambda obj, action: action(obj), self._actions, obj)

    def signature[**P](self, fn: Callable[Concatenate[T, P], T]) -> Callable[Concatenate[T, P], T]:
        """Give the flow the call signature of `fn`, so type checkers check its run inputs.

        Use it as a decorator on a stub that declares the subject positional-only
        and every run input keyword-only. The stub must match the inputs of the
        steps by name and by being required, or `InvalidInputError` is raised.

        Example:
        ```python
        >>> from pyflowstep import Input, step
        >>> @step
        ... def add_tax(price: float, rate: float = Input(), bonus: float = Input(default=0.0)):
        ...     return price * (1 + rate) + bonus
        >>> @add_tax().signature
        ... def taxed(price: float, /, *, rate: float, bonus: float = ...) -> float: ...
        >>> taxed(100.0, rate=0.25)
        125.0
        >>> @add_tax().signature
        ... def wrong(price: float, /) -> float: ...
        Traceback (most recent call last):
        ...
        pyflowstep.exceptions.InvalidInputError: Signature 'wrong' does not match the flow: ...

        ```

        """
        check_signature(self._actions, fn)

        @wraps(fn)
        def call(obj: T, /, *args: P.args, **kwargs: P.kwargs) -> T:  # noqa: ARG001
            return self(obj, **kwargs)  # check_signature leaves no other positional parameter

        return call

    def __rshift__(self, other: Action[T]) -> "Flow[T]":
        if not callable(other):
            return NotImplemented
        return Flow(*self._actions, *_actions_of(other))

    def __rrshift__(self, other: Action[T]) -> "Flow[T]":
        if not callable(other):
            return NotImplemented
        return Flow(*_actions_of(other), *self._actions)

    def __len__(self) -> int:
        return len(self._actions)

    def __iter__(self) -> Iterator[Action[T]]:
        return iter(self._actions)

    def __bool__(self) -> bool:
        return True

    def __repr__(self) -> str:
        return f"Flow({' >> '.join(map(action_name, self._actions))})"


def compose[T](*actions: Action[T]) -> Flow[T]:
    """Combine actions and flows into one flat `Flow`, left to right.

    `compose(a, b, c)` is equivalent to `Flow() >> a >> b >> c`. Nested flows
    are flattened, so the result lists every underlying step.

    Example:
    ```python
    >>> add_one = Flow[int](lambda n: n + 1)
    >>> square = lambda n: n * n
    >>> compose(add_one, square, add_one)(2)
    10
    >>> compose()(5)
    5

    ```

    """
    return reduce(Flow.__rshift__, actions, Flow[T]())


def action_name(action: Callable[..., Any]) -> str:
    """Return a human-readable name for an action, used by `repr` and error notes.

    Example:
    ```python
    >>> action_name(len)
    'len'
    >>> action_name(lambda x: x)
    '<lambda>'
    >>> action_name(Flow(len, abs))
    'Flow(len >> abs)'

    ```

    """
    if isinstance(action, Flow):
        return repr(action)
    return getattr(action, "__name__", None) or repr(action)


def _actions_of[T](obj: Action[T] | Flow[T]) -> tuple[Action[T], ...]:
    return obj.actions if isinstance(obj, Flow) else (obj,)
