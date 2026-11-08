"""Generate JSON Schemas describing steps and whole flow definitions.

The schemas describe the exact shape accepted by `FlowCompiler`, so they can be
handed to a form builder, a validator, or an LLM that writes flows as JSON.
"""

from collections.abc import Callable, Mapping
from typing import Any

from pyvocabulary import JSON_SCHEMA_DIALECT, call_json_schema, json_schema_of

__all__ = [
    "JSON_SCHEMA_DIALECT",
    "get_flow_json_schema",
    "get_json_schema",
    "get_step_json_schema",
]


def get_json_schema(annotation: Any) -> dict[str, Any]:
    """Return the JSON Schema of a Python type annotation.

    Unknown or unannotated types map to `{}`, which accepts any value. A type
    marked with `Process(fn)` is described by what `fn` accepts, because that is
    what the JSON has to send. See `pyvocabulary.json_schema_of`.

    Example:
    ```python
    >>> from typing import Literal
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
    return json_schema_of(annotation)


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
    return call_json_schema(name, step)


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
