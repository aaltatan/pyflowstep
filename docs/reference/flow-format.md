# Flow definition format

This is what a [`FlowCompiler`](../guide/compiling.md) accepts.

## JSON

A definition is a **list** of step dictionaries, run in order:

```json
[
  {"name": "navigate", "args": ["https://shop.example/login"]},
  {"name": "fill", "args": ["#email"], "kwargs": {"value": "qa@shop.example"}},
  {"name": "click", "kwargs": {"selector": "#submit"}}
]
```

| Key | Type | Required | Default |
| --- | --- | --- | --- |
| `name` | string | yes | |
| `args` | array | no | `[]` |
| `kwargs` | object with string keys | no | `{}` |

- No other key is allowed.
- `name` must be a step in the compiler's mapping (visible steps of a registry).
- `args` and `kwargs` are bound to the step's parameters like a Python call
  `step(*args, **kwargs)`; then each step's [`Process`](../guide/arguments.md) markers run.
- An empty list is a valid definition: the identity flow.

## TOML

The same list, as an array of tables named `steps`:

```toml
[[steps]]
name = "navigate"
args = ["https://shop.example/login"]

[[steps]]
name = "fill"
args = ["#email"]
kwargs = { value = "qa@shop.example" }

[[steps]]
name = "click"
kwargs = { selector = "#submit" }
```

A TOML document without `steps` is an `InvalidFlowDefinitionError`. Other top-level keys
are ignored, so a file may carry metadata such as `title = "Login"`.

## What is checked

| Check | Error | Path note |
| --- | --- | --- |
| the definition is a list (not a string, bytes or object) | `InvalidFlowDefinitionError` | none (the message says `at $`) |
| each step is an object with only `name`, `args`, `kwargs` of the right types | `InvalidFlowDefinitionError` | `at $[i]` |
| `name` exists | `StepDoesNotExistError` | `at $[i]` |
| the arguments fit the signature | `ArgumentError` subclasses | `at $[i]` |
| the processors accept the values | `ProcessArgumentError` | `at $[i]` |
| (from a file) the file parses and its suffix is known | `InvalidFlowDefinitionError`, `UnsupportedFlowFormatError` | `in <path>` |

```python
from pyflowstep import FlowCompiler, InvalidFlowDefinitionError, validate_step_dict

assert validate_step_dict({"name": "click", "args": ["#go"]}) == {"name": "click", "args": ["#go"]}

for bad, problem in [
    ({"name": "click", "selector": "#go"}, "unknown keys ['selector']"),
    ({"args": ["#go"]}, "'name' is required and must be a string"),
    ({"name": "click", "args": "#go"}, "'args' must be a list"),
    ({"name": "click", "kwargs": ["#go"]}, "'kwargs' must be an object"),
    ("click", "a step must be an object"),
]:
    try:
        validate_step_dict(bad, "$[0]")
    except InvalidFlowDefinitionError as error:
        assert str(error).startswith(f"Invalid step at $[0]: {problem}")

try:
    FlowCompiler({}).compile({"name": "click"})
except InvalidFlowDefinitionError as error:
    assert str(error).startswith("Invalid flow definition at $: expected a list of steps")

assert FlowCompiler({}).compile([])("unchanged") == "unchanged"
```

## Values JSON cannot carry

Parameters marked with [`Depends`](../guide/dependencies.md) or
[`Input`](../guide/inputs.md) are not arguments: a definition cannot set them, and the
[JSON Schema](../guide/json-schema.md) leaves them out. The subject is given when the
flow runs.
