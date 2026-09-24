"""The `Flow` type: an immutable, composable pipeline of `T -> T` actions."""

from collections.abc import Callable, Iterator
from functools import reduce
from typing import Any

type Action[T] = Callable[[T], T]


class Flow[T]:
    """An immutable sequence of actions applied, in order, to a single subject.

    A flow is a callable `T -> T`. Calling it threads the subject through every
    action: the output of one action is the input of the next. Flows compose
    with `>>`, which always returns a *new* flow and never mutates its operands.

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

    def __call__(self, obj: T) -> T:
        return reduce(lambda obj, action: action(obj), self._actions, obj)

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
