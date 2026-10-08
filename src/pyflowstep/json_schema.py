"""Generate JSON Schemas describing steps and whole flow definitions.

The schemas describe the exact shape accepted by `FlowCompiler`, so they can be
handed to a form builder, a validator, or an LLM that writes flows as JSON.
"""

from collections.abc import Callable, Mapping
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from inspect import Parameter, get_annotations, signature
from types import NoneType, UnionType
from typing import (
    Annotated,
    Any,
    Literal,
    NotRequired,
    Required,
    TypeAliasType,
    Union,
    get_args,
    get_origin,
    is_typeddict,
)
from uuid import UUID

from .annotations import annotated_metadata, resolved_annotations
from .parsers import Parse, input_annotation

JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"

_SCALAR_SCHEMAS: dict[Any, dict[str, Any]] = {
    str: {"type": "string"},
    int: {"type": "integer"},
    float: {"type": "number"},
    Decimal: {"type": "number"},
    bool: {"type": "boolean"},
    None: {"type": "null"},
    NoneType: {"type": "null"},
    datetime: {"type": "string", "format": "date-time"},
    date: {"type": "string", "format": "date"},
    time: {"type": "string", "format": "time"},
    UUID: {"type": "string", "format": "uuid"},
}

_ARRAY_TYPES = (list, tuple, set, frozenset)
_WRAPPER_ORIGINS = (Annotated, Required, NotRequired)
_POSITIONAL_KINDS = (Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD)
_KEYWORD_KINDS = (Parameter.POSITIONAL_OR_KEYWORD, Parameter.KEYWORD_ONLY)


def get_json_schema(annotation: Any) -> dict[str, Any]:
    """Return the JSON Schema of a Python type annotation.

    Unknown or unannotated types map to `{}`, which accepts any value. A type
    marked with `Parse(fn)` is described by what `fn` accepts, because that is
    what the JSON has to send.

    Example:
    ```python
    >>> get_json_schema(int)
    {'type': 'integer'}
    >>> get_json_schema(list[str])
    {'type': 'array', 'items': {'type': 'string'}}
    >>> get_json_schema(Literal["oat", "soy"])
    {'enum': ['oat', 'soy'], 'type': 'string'}
    >>> get_json_schema(int | None)
    {'anyOf': [{'type': 'integer'}, {'type': 'null'}]}

    ```

    """
    origin = get_origin(annotation)

    if is_typeddict(annotation):
        return _typeddict_schema(annotation)

    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return _enum_schema([member.value for member in annotation])

    if isinstance(annotation, TypeAliasType):
        return get_json_schema(annotation.__value__)

    if origin in _WRAPPER_ORIGINS:
        return get_json_schema(_sent_annotation(annotation))

    if origin is Literal:
        return _enum_schema(list(get_args(annotation)))

    if origin in (Union, UnionType):
        return {"anyOf": [get_json_schema(arg) for arg in get_args(annotation)]}

    if (origin or annotation) in _ARRAY_TYPES:
        return _array_schema(get_args(annotation))

    if (origin or annotation) is dict:
        return _dict_schema(get_args(annotation))

    return dict(_SCALAR_SCHEMAS.get(annotation, {}))


def get_step_json_schema(name: str, step: Callable[..., Any]) -> dict[str, Any]:
    """Return the JSON Schema of one step dictionary, e.g. `{"name": ..., "args": [...]}`.

    `step` is a step factory (as returned by `step`, `tap` or a registry), whose
    signature excludes the subject. Positional parameters are described under
    `args` (via `prefixItems`), keyword-capable parameters under `kwargs`, and
    the step docstring becomes the description.

    Example:
    ```python
    >>> from pyflowstep import step
    >>> @step
    ... def fill(page, selector: str, value: str = "") -> object:
    ...     '''Type a value into a field.'''
    ...     return page
    >>> schema = get_step_json_schema("fill", fill)
    >>> schema["properties"]["name"]
    {'const': 'fill'}
    >>> schema["properties"]["args"]["prefixItems"]
    [{'type': 'string'}, {'type': 'string', 'default': ''}]
    >>> schema["description"]
    'Type a value into a field.'

    ```

    """
    parameters = list(signature(step).parameters.values())
    annotations = resolved_annotations(step)

    def parameter_schema(parameter: Parameter) -> dict[str, Any]:
        schema = get_json_schema(annotations.get(parameter.name, Any))
        if parameter.default is not Parameter.empty and _is_json_value(parameter.default):
            schema["default"] = parameter.default
        return schema

    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "name": {"const": name},
            "args": _args_schema(parameters, parameter_schema),
            "kwargs": _kwargs_schema(parameters, parameter_schema),
        },
        "required": ["name"],
        "additionalProperties": False,
    }

    if step.__doc__:
        schema["description"] = step.__doc__.strip()

    return schema


def get_flow_json_schema(steps: Mapping[str, Callable[..., Any]]) -> dict[str, Any]:
    """Return the JSON Schema of a whole flow definition: a list of step dictionaries.

    Pass `registry.steps` (or any name-to-step mapping given to `FlowCompiler`).

    Example:
    ```python
    >>> from pyflowstep import step
    >>> @step
    ... def wait(page, selector: str) -> object:
    ...     return page
    >>> schema = get_flow_json_schema({"wait": wait})
    >>> schema["type"], len(schema["items"]["oneOf"])
    ('array', 1)

    ```

    """
    return {
        "$schema": JSON_SCHEMA_DIALECT,
        "type": "array",
        "items": {"oneOf": [get_step_json_schema(name, step) for name, step in steps.items()]},
    }


def _args_schema(
    parameters: list[Parameter],
    parameter_schema: Callable[[Parameter], dict[str, Any]],
) -> dict[str, Any]:
    positional = [parameter for parameter in parameters if parameter.kind in _POSITIONAL_KINDS]
    var_positional = next(
        (parameter for parameter in parameters if parameter.kind is Parameter.VAR_POSITIONAL),
        None,
    )
    return {
        "type": "array",
        "prefixItems": [parameter_schema(parameter) for parameter in positional],
        "items": parameter_schema(var_positional) if var_positional else False,
    }


def _kwargs_schema(
    parameters: list[Parameter],
    parameter_schema: Callable[[Parameter], dict[str, Any]],
) -> dict[str, Any]:
    keyword = [parameter for parameter in parameters if parameter.kind in _KEYWORD_KINDS]
    var_keyword = next(
        (parameter for parameter in parameters if parameter.kind is Parameter.VAR_KEYWORD),
        None,
    )
    return {
        "type": "object",
        "properties": {parameter.name: parameter_schema(parameter) for parameter in keyword},
        "required": [
            parameter.name
            for parameter in keyword
            if parameter.kind is Parameter.KEYWORD_ONLY and parameter.default is Parameter.empty
        ],
        "additionalProperties": parameter_schema(var_keyword) if var_keyword else False,
    }


def _enum_schema(values: list[Any]) -> dict[str, Any]:
    schema: dict[str, Any] = {"enum": values}
    if values and all(isinstance(value, str) for value in values):
        schema["type"] = "string"
    return schema


def _array_schema(args: tuple[Any, ...]) -> dict[str, Any]:
    return {"type": "array", "items": get_json_schema(args[0]) if args else {}}


def _dict_schema(args: tuple[Any, ...]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": get_json_schema(args[1]) if args else {}}


def _typeddict_schema(annotation: Any) -> dict[str, Any]:
    annotations = get_annotations(annotation)
    return {
        "type": "object",
        "properties": {name: get_json_schema(typ) for name, typ in annotations.items()},
        "required": [name for name in annotations if name in annotation.__required_keys__],
    }


def _sent_annotation(annotation: Any) -> Any:
    """Return the type the JSON must send for an `Annotated`/`Required`/`NotRequired` type."""
    parser = next(
        (item for item in annotated_metadata(annotation) if isinstance(item, Parse)), None
    )
    sent = input_annotation(parser) if parser else None
    return get_args(annotation)[0] if sent is None else sent


def _is_json_value(value: Any) -> bool:
    return value is None or isinstance(value, str | int | float | bool | list | dict)
