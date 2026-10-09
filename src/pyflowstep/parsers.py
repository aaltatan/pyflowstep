"""Argument parsing: turn the raw values a step receives into the objects it wants.

Flows often come from JSON or a web form, where every value is a string,
number, boolean, list, dict or null, while steps want dates, decimals, enums,
clean text or loaded data. Mark the parameter with `Parse(fn)` inside
`Annotated` and `fn` is applied to the value when the flow is built:

    def wait(page: Page, selector: str, timeout: Annotated[float, Parse(float)] = 5.0) -> Page: ...

    wait("#result", "10")  # timeout is 10.0

Name a parsed type once with a `type` alias and reuse it in many steps:

    type Text = Annotated[str, Parse(str.strip), Parse(str.lower)]
    type Rows = Annotated[list[Row], Parse(load_rows)]  # the JSON passes a path

Parsing happens once, when a step is built, so a bad value fails before the
flow runs. Default values are never parsed.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import reduce
from inspect import BoundArguments, Parameter, signature
from typing import Any

from .annotations import annotated_metadata, resolved_annotations
from .exceptions import InvalidParserError, ParseArgumentError


@dataclass(frozen=True, slots=True)
class Parse:
    """Mark a step parameter: apply `fn` to the value passed for it.

    Use it inside `Annotated`, directly or through a `type` alias. Several
    markers on one parameter run left to right. On `*args` the function is
    applied to each item, on `**kwargs` to each value.

    Example:
    ```python
    >>> from typing import Annotated
    >>> from pyflowstep import step
    >>> type Text = Annotated[str, Parse(str.strip), Parse(str.lower)]
    >>> @step
    ... def add(items: list, name: Text, amount: Annotated[int, Parse(int)] = 1) -> list:
    ...     return [*items, (name, amount)]
    >>> add("  Tea ", "2")([])
    [('tea', 2)]
    >>> add(" Milk")([])
    [('milk', 1)]
    >>> add("tea", "two")
    Traceback (most recent call last):
    ...
    pyflowstep.exceptions.ParseArgumentError: Argument 'amount' with value 'two' failed to parse...

    ```

    """

    fn: Callable[[Any], Any]

    def __post_init__(self) -> None:
        if not callable(self.fn):
            msg = f"Parse needs a callable, got {self.fn!r}"
            raise InvalidParserError(msg)


def find_parsers(fn: Callable[..., Any], step_name: str) -> dict[str, tuple[Parse, ...]]:
    """Return the `Parse` markers of every parameter of a step function that has some.

    Raises:
        InvalidParserError: If a marker is used as a default value, or sits on the subject.

    Example:
    ```python
    >>> from typing import Annotated
    >>> def wait(page, selector: str, timeout: Annotated[float, Parse(float)] = 5.0): ...
    >>> find_parsers(wait, "wait")
    {'timeout': (Parse(fn=<class 'float'>),)}

    ```

    """
    parameters = signature(fn).parameters
    annotations = resolved_annotations(fn)

    for name, parameter in parameters.items():
        if isinstance(parameter.default, Parse):
            msg = (
                f"Step '{step_name}' uses Parse as the default of '{name}'; write it as "
                f"`{name}: Annotated[<type>, Parse(...)]` so the parameter can keep a real default"
            )
            raise InvalidParserError(msg)

    found = {name: _markers(annotations.get(name)) for name in parameters}
    parsers = {name: markers for name, markers in found.items() if markers}
    subject = next(iter(parameters))

    if subject in parsers:
        msg = f"Step '{step_name}' cannot parse its subject '{subject}'"
        raise InvalidParserError(msg)

    return parsers


def parse_arguments(
    parsers: Mapping[str, tuple[Parse, ...]],
    bound: BoundArguments,
) -> BoundArguments:
    """Return new bound arguments with every marked value parsed.

    Values of unmarked parameters are kept as they are, and the original
    `bound` object is left untouched.

    Raises:
        ParseArgumentError: If a parser raises; the original exception is chained.

    Example:
    ```python
    >>> def brew(shots: int, *toppings: str, **extras: str): ...
    >>> bound = signature(brew).bind("2", " foam ", " cocoa ", size="L", note="Hot")
    >>> strip, lower = (Parse(str.strip),), (Parse(str.lower),)
    >>> parsers = {"shots": (Parse(int),), "toppings": strip, "extras": lower}
    >>> parse_arguments(parsers, bound).arguments
    {'shots': 2, 'toppings': ('foam', 'cocoa'), 'extras': {'size': 'l', 'note': 'hot'}}

    ```

    """
    parameters = bound.signature.parameters
    parsed = {
        name: _parse_parameter(parsers.get(name, ()), parameters[name], value)
        for name, value in bound.arguments.items()
    }
    return BoundArguments(bound.signature, parsed)  # type: ignore[arg-type]


def input_annotation(parser: Parse) -> Any:
    """Return the annotation of the value `parser` accepts, or `None` if it has none.

    The JSON schema uses it to describe what the JSON must send.

    Example:
    ```python
    >>> def load_rows(path: str) -> list[dict]: ...
    >>> input_annotation(Parse(load_rows))
    <class 'str'>
    >>> input_annotation(Parse(int)) is None
    True

    ```

    """
    try:
        first = next(iter(signature(parser.fn).parameters), None)
    except (TypeError, ValueError):  # builtins without a signature
        return None

    return resolved_annotations(parser.fn).get(first) if first else None


def _markers(annotation: Any) -> tuple[Parse, ...]:
    return tuple(item for item in annotated_metadata(annotation) if isinstance(item, Parse))


def _parse_parameter(markers: tuple[Parse, ...], parameter: Parameter, value: Any) -> Any:
    match parameter.kind:
        case Parameter.VAR_POSITIONAL:
            return tuple(_parse_value(markers, parameter.name, item) for item in value)
        case Parameter.VAR_KEYWORD:
            return {key: _parse_value(markers, key, item) for key, item in value.items()}
        case _:
            return _parse_value(markers, parameter.name, value)


def _parse_value(markers: tuple[Parse, ...], name: str, value: Any) -> Any:
    try:
        return reduce(lambda current, marker: marker.fn(current), markers, value)
    except Exception as error:
        msg = f"Argument '{name}' with value {value!r} failed to parse, {error}"
        raise ParseArgumentError(msg) from error
