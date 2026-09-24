"""Argument processors: transform raw step arguments before a step is built.

Processors are most useful when a flow comes from JSON, where every value is a
string, number, boolean, list, dict or null. They turn those raw values into
the rich objects your step functions expect (dates, enums, decimals, ...).

The `processors` option of a registry accepts:

- `None`: arguments are passed through untouched (the default).
- a callable: applied to every argument.
- a mapping from parameter name to callable: applied to those arguments only.
  The key `...` (Ellipsis) means "every argument not named here".

    processors=float
    processors={"timeout": float}
    processors={"pumps": int, ...: str.strip}

A processor for a parameter applies whether the value was passed positionally
or by keyword. For `*args` it applies to each item, and for `**kwargs` each
extra keyword name is looked up individually.
"""

from collections.abc import Callable, Mapping
from inspect import BoundArguments, Parameter
from types import EllipsisType
from typing import Any

from .exceptions import InvalidProcessorsError, ProcessArgumentError


def processor_lookup(
    processors: Callable[[Any], Any] | Mapping[str | EllipsisType, Callable[[Any], Any]],
    parameters: Mapping[str, Parameter],
    step_name: str,
) -> Callable[[str], Callable[[Any], Any] | None]:
    """Validate a `processors` option and turn it into a name-to-processor lookup.

    Mapping keys are checked against `parameters`, so a typo fails at
    registration instead of silently never running. Steps accepting `**kwargs`
    allow any key.

    Raises:
        InvalidProcessorsError: If the option has the wrong type, a processor is
            not callable, or a key names no parameter.

    Example:
    ```python
    >>> from inspect import signature
    >>> parameters = signature(lambda flavor, pumps: None).parameters
    >>> lookup = processor_lookup({"pumps": int, ...: str.strip}, parameters, "add_syrup")
    >>> lookup("pumps"), lookup("flavor")
    (<class 'int'>, <method 'strip' of 'str' objects>)
    >>> lookup = processor_lookup({"pumps": int}, parameters, "add_syrup")
    >>> lookup("flavor") is None
    True
    >>> processor_lookup({"pums": int}, parameters, "add_syrup")
    Traceback (most recent call last):
    ...
    pyflowstep.exceptions.InvalidProcessorsError: Processors of step 'add_syrup' name unknown ...

    ```

    """
    if isinstance(processors, Mapping):
        _validate_mapping(processors, parameters, step_name)
        rest = processors.get(...)
        return lambda name: processors.get(name, rest)

    if callable(processors):
        return lambda _: processors

    msg = (
        f"Processors of step '{step_name}' must be a callable or a mapping of "
        f"parameter names to callables, got {processors!r}"
    )
    raise InvalidProcessorsError(msg)


def process_arguments(
    lookup: Callable[[str], Callable[[Any], Any] | None],
    bound: BoundArguments,
) -> BoundArguments:
    """Return new bound arguments with every value run through its processor.

    Values without a processor are kept as they are, and the original `bound`
    object is left untouched.

    Raises:
        ProcessArgumentError: If any processor raises; the original exception is chained.

    Example:
    ```python
    >>> from inspect import signature
    >>> def brew(shots: int, *toppings: str, **extras: str): ...
    >>> bound = signature(brew).bind("2", " foam ", " cocoa ", size="L", note=" hot ")
    >>> lookup = {"shots": int, "toppings": str.strip, "size": str.lower}.get
    >>> process_arguments(lookup, bound).arguments
    {'shots': 2, 'toppings': ('foam', 'cocoa'), 'extras': {'size': 'l', 'note': ' hot '}}

    ```

    """
    parameters = bound.signature.parameters
    processed = {
        name: _process_parameter(lookup, parameters[name], value)
        for name, value in bound.arguments.items()
    }
    return BoundArguments(bound.signature, processed)  # type: ignore[arg-type]


def _validate_mapping(
    processors: Mapping[Any, Any],
    parameters: Mapping[str, Parameter],
    step_name: str,
) -> None:
    if not_callable := sorted(str(key) for key, fn in processors.items() if not callable(fn)):
        msg = f"Processors of step '{step_name}' must be callables, not for {not_callable}"
        raise InvalidProcessorsError(msg)

    if any(parameter.kind is Parameter.VAR_KEYWORD for parameter in parameters.values()):
        return

    if unknown := sorted(map(str, processors.keys() - parameters.keys() - {...})):
        msg = (
            f"Processors of step '{step_name}' name unknown parameters {unknown}, "
            f"available parameters: {', '.join(parameters) or '(none)'}"
        )
        raise InvalidProcessorsError(msg)


def _process_parameter(
    lookup: Callable[[str], Callable[[Any], Any] | None],
    parameter: Parameter,
    value: Any,
) -> Any:
    match parameter.kind:
        case Parameter.VAR_POSITIONAL:
            return tuple(_process_value(lookup, parameter.name, item) for item in value)
        case Parameter.VAR_KEYWORD:
            return {key: _process_value(lookup, key, item) for key, item in value.items()}
        case _:
            return _process_value(lookup, parameter.name, value)


def _process_value(
    lookup: Callable[[str], Callable[[Any], Any] | None],
    name: str,
    value: Any,
) -> Any:
    process = lookup(name)

    if process is None:
        return value

    try:
        return process(value)
    except Exception as error:
        msg = f"Argument '{name}' with value {value!r} failed to process, {error}"
        raise ProcessArgumentError(msg) from error
