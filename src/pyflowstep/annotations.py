"""Read the annotations that carry markers such as `Parse` and `Depends`."""

from collections.abc import Callable
from functools import partial
from inspect import get_annotations, isroutine
from typing import Annotated, Any, TypeAliasType, get_args, get_origin


def resolved_annotations(fn: Callable[..., Any]) -> dict[str, Any]:
    """Return the annotations describing a call to `fn`, with strings evaluated when possible.

    For a class this is its `__init__`, for a callable object its `__call__`,
    and for a `functools.partial` the function it wraps.

    Example:
    ```python
    >>> def wait(page, selector: "str", timeout: float = 5.0): ...
    >>> resolved_annotations(wait)
    {'selector': <class 'str'>, 'timeout': <class 'float'>}

    ```

    """
    target = _annotated_function(fn)

    try:
        return get_annotations(target, eval_str=True)
    except NameError:
        return get_annotations(target)


def annotated_metadata(annotation: Any) -> tuple[Any, ...]:
    """Return the extra arguments of `Annotated[...]`, looking through `type` aliases.

    Example:
    ```python
    >>> type Port = Annotated[int, "tcp", 8080]
    >>> annotated_metadata(Port)
    ('tcp', 8080)
    >>> annotated_metadata(int)
    ()

    ```

    """
    while isinstance(annotation, TypeAliasType):
        annotation = annotation.__value__

    return get_args(annotation)[1:] if get_origin(annotation) is Annotated else ()


def _annotated_function(fn: Callable[..., Any]) -> Callable[..., Any]:
    if isinstance(fn, partial):
        return _annotated_function(fn.func)

    if isinstance(fn, type):
        return fn.__init__

    return fn if isroutine(fn) else type(fn).__call__
