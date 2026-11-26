# JSON Schema

pyflowstep generates [JSON Schema](https://json-schema.org/) (draft 2020-12) of your flow
language from the step signatures. It describes exactly what
[`FlowCompiler.compile`](compiling.md) accepts, so hand it to:

- a **flow editor** that builds forms for each step,
- a **validator** that rejects bad definitions before they are saved,
- an **LLM** that writes flows from a sentence ("log in, open November's payroll and
  export it"),
- your **API docs**.

| Function | Describes |
| --- | --- |
| `get_flow_json_schema(steps)` | a whole flow definition: a list of any of the steps |
| `get_step_json_schema(name, step)` | one step dictionary |
| `get_json_schema(annotation)` | one Python type |

## Example: describing a QA scenario language

```python
from typing import Annotated, Literal

from pyargprocessors import Process

from pyflowstep import Depends, Input, StepsRegistry, get_flow_json_schema, get_step_json_schema


class Page:
    actions: list[str]


def get_screenshot_dir() -> str:
    return "/tmp/shots"


qa = StepsRegistry[Page]()


@qa.tap()
def navigate(page: Page, url: str) -> None:
    """Open a URL."""


@qa.tap()
def fill(page: Page, selector: str, value: str = "", *, clear: bool = True) -> None:
    """Type a value into a field."""


@qa.tap()
def wait(page: Page, seconds: Annotated[float, Process(float)], until: Literal["load", "idle"] = "load") -> None:
    """Wait for the page."""


@qa.tap()
def screenshot(page: Page, name: str, folder: str = Depends(get_screenshot_dir), user: str = Input()) -> None:
    """Save a screenshot named after the run's user."""


schema = get_flow_json_schema(qa.steps)

assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
assert schema["type"] == "array"
assert [one["properties"]["name"] for one in schema["items"]["oneOf"]] == [
    {"const": "navigate"},
    {"const": "fill"},
    {"const": "wait"},
    {"const": "screenshot"},
]
```

A flow is an `array` whose items are `oneOf` the step schemas, one per visible step.

## One step

Each step is an object with a constant `name` and optional `args` and `kwargs`:

```python
fill_schema = get_step_json_schema("fill", qa["fill"])

assert fill_schema["required"] == ["name"]
assert fill_schema["additionalProperties"] is False
assert fill_schema["description"] == "Type a value into a field."
assert fill_schema["properties"]["args"] == {
    "type": "array",
    "prefixItems": [{"type": "string"}, {"type": "string", "default": ""}],
    "items": False,
}
assert fill_schema["properties"]["kwargs"]["properties"] == {
    "selector": {"type": "string"},
    "value": {"type": "string", "default": ""},
    "clear": {"type": "boolean", "default": True},
}
```

- **`args`** lists the parameters that can be passed positionally, in order, with
  `prefixItems`; `"items": false` forbids extra items.
- **`kwargs`** lists every parameter that can be passed by name, keyword-only ones
  included (`clear`). Its `required` is empty, because a required parameter may come
  through `args` instead; the compiler still reports a missing one.
- Defaults that are plain JSON values are included.
- The description is the docstring, or the registry's `description=`.

### Only real arguments

The subject, [`Depends`](dependencies.md) parameters and [`Input`](inputs.md) parameters
are not arguments, so they are not in the schema:

```python
shot = get_step_json_schema("screenshot", qa["screenshot"])

assert list(shot["properties"]["kwargs"]["properties"]) == ["name"]
```

### Processed arguments

A parameter with a [`Process`](arguments.md) marker is described by what the
**processor accepts**, because that is what the JSON has to send. `float` has no
annotated parameter, so `seconds` falls back to its own type:

```python
wait_args = get_step_json_schema("wait", qa["wait"])["properties"]["args"]["prefixItems"]

assert wait_args == [
    {"type": "number"},
    {"enum": ["load", "idle"], "type": "string", "default": "load"},
]
```

## Supported types

`get_json_schema(annotation)` maps Python annotations:

| Python annotation | JSON Schema |
| --- | --- |
| `str`, `int`, `float`, `bool`, `None` | `string`, `integer`, `number`, `boolean`, `null` |
| `Decimal` | `number` |
| `datetime`, `date`, `time`, `UUID` | `string` with format `date-time`, `date`, `time`, `uuid` |
| `list[T]`, `set[T]`, `frozenset[T]`, `tuple[T, ...]` | `array` of `T` |
| `dict[K, V]` | `object` with `V` as `additionalProperties` |
| `Literal[...]`, `Enum` subclasses | `enum` of the values, plus `"type": "string"` when all are strings |
| `A \| B`, `Optional[A]` | `anyOf` |
| `TypedDict` | `object` with `properties` and `required` |
| `Annotated[T, ...]`, `type` aliases | the schema of `T` |
| unknown or missing | `{}` (anything) |

```python
from datetime import date

from pyflowstep import get_json_schema

assert get_json_schema(date) == {"type": "string", "format": "date"}
assert get_json_schema(list[str]) == {"type": "array", "items": {"type": "string"}}
assert get_json_schema(int | None) == {"anyOf": [{"type": "integer"}, {"type": "null"}]}
```

## Validating definitions

Any draft 2020-12 validator works. With [`jsonschema`](https://pypi.org/project/jsonschema/):

```py
from jsonschema import Draft202012Validator

validator = Draft202012Validator(get_flow_json_schema(qa.steps))

if errors := [error.message for error in validator.iter_errors(definition)]:
    return {"ok": False, "errors": errors}

flow = FlowCompiler(qa.steps).compile(definition)  # also runs processors
```

## Letting an LLM write flows

The flow schema is a ready-made tool input schema. With the Anthropic SDK:

```py
import anthropic

client = anthropic.Anthropic()

response = client.messages.create(
    model="claude-opus-5-5",
    max_tokens=2048,
    tools=[
        {
            "name": "write_scenario",
            "description": "Write a browser test scenario as a list of steps.",
            "input_schema": {
                "type": "object",
                "properties": {"steps": get_flow_json_schema(qa.steps)},
                "required": ["steps"],
            },
        }
    ],
    tool_choice={"type": "tool", "name": "write_scenario"},
    messages=[{"role": "user", "content": "Open the login page, type the demo email and wait until idle"}],
)

scenario = FlowCompiler(qa.steps).compile(response.content[0].input["steps"])
```

Step docstrings become schema descriptions, so a precise docstring is a precise prompt.
Compile what the model returns inside a `try`.
