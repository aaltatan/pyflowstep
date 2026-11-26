# Compiling flows from JSON and TOML

When flows are **data** (onboarding sequences per plan, test scenarios written by QA,
document workflows configured per customer) describe them as a list of steps and compile
them:

```py
FlowCompiler(steps: Mapping[str, StepFactory], /)
compiler.compile(definition) -> Flow
compiler.compile_file(path) -> Flow
```

`steps` is usually `registry.steps`. There is no `eval`: a definition can only name your
steps and pass them arguments.

## The definition format

A definition is a **list of step dictionaries**, run in order:

```json
[
  {"name": "create_account", "args": ["starter"]},
  {"name": "send_email", "kwargs": {"template": "welcome"}},
  {"name": "schedule_call", "args": [], "kwargs": {"days": 3}}
]
```

| Key | Required | Meaning |
| --- | --- | --- |
| `name` | yes | a step name from the compiler's mapping |
| `args` | no, default `[]` | positional arguments |
| `kwargs` | no, default `{}` | keyword arguments |

No other key is allowed. The [flow format reference](../reference/flow-format.md) has the
details, and `StepDict` / `FlowDefinition` describe it for type checkers.

## Example: onboarding new customers per plan

A SaaS company onboards each new customer with a sequence that depends on the plan. The
product team edits the sequences; the code only provides the steps.

```python
from dataclasses import dataclass, field

from pyflowstep import FlowCompiler, StepsRegistry


@dataclass
class Customer:
    email: str
    plan: str = ""
    features: set[str] = field(default_factory=set)
    emails: list[str] = field(default_factory=list)
    tasks: list[str] = field(default_factory=list)


onboarding = StepsRegistry[Customer]()


@onboarding.tap()
def set_plan(customer: Customer, plan: str) -> None:
    """Put the customer on a plan."""
    customer.plan = plan


@onboarding.tap()
def enable(customer: Customer, *features: str) -> None:
    """Turn features on."""
    customer.features.update(features)


@onboarding.tap()
def send_email(customer: Customer, template: str) -> None:
    """Send one of the onboarding email templates."""
    customer.emails.append(template)


@onboarding.tap()
def schedule_call(customer: Customer, days: int, with_team: str = "success") -> None:
    """Book a call with a team, some days from now."""
    customer.tasks.append(f"call with {with_team} in {days} days")


compiler = FlowCompiler(onboarding.steps)

starter = compiler.compile(
    [
        {"name": "set_plan", "args": ["starter"]},
        {"name": "enable", "args": ["projects", "invoices"]},
        {"name": "send_email", "kwargs": {"template": "welcome"}},
    ]
)

customer = starter(Customer("rana@example.com"))

assert customer.plan == "starter"
assert customer.features == {"projects", "invoices"}
assert repr(starter) == "Flow(set_plan >> enable >> send_email)"
```

A compiled flow is an ordinary flow: it composes with Python steps and other compiled
flows.

```python
enterprise = starter >> schedule_call(2, with_team="solutions")

assert enterprise(Customer("omar@example.com")).tasks == ["call with solutions in 2 days"]
```

`compile` takes already-parsed data, so the definition can come from an API payload, a
database column, or any file format.

## Errors point at the step

Everything is checked while compiling, before any step runs: the list shape, each step
dictionary, unknown names, arguments and [processors](arguments.md). Each error gets an
exception **note with the JSON path** of the step:

```python
from pyflowstep import InvalidFlowDefinitionError, MissingArgumentError, StepDoesNotExistError

try:
    compiler.compile([{"name": "set_plan", "args": ["pro"]}, {"name": "send_mail", "args": ["welcome"]}])
except StepDoesNotExistError as error:
    assert str(error) == (
        "Step 'send_mail' does not exist. Available steps: enable, schedule_call, send_email, set_plan"
    )
    assert error.__notes__ == ["at $[1]"]

try:
    compiler.compile([{"name": "schedule_call"}])
except MissingArgumentError as error:
    assert error.__notes__ == ["at $[0]"]

try:
    compiler.compile([{"name": "enable", "arguments": ["sso"]}])
except InvalidFlowDefinitionError as error:
    assert str(error).startswith("Invalid step at $[0]: unknown keys ['arguments']")
```

| Problem | Exception |
| --- | --- |
| the definition is not a list, a step is not an object, unknown keys, wrong types | `InvalidFlowDefinitionError` |
| unknown or hidden step name | `StepDoesNotExistError`, listing the available steps |
| missing, extra or duplicated arguments | `MissingArgumentError`, `TooManyArgumentsError`, ... |
| a processor rejects a value | `ProcessArgumentError` (from pyargprocessors) |

`validate_step_dict(item, path="$")` checks one step dictionary on its own, for example
in a form that edits one step at a time.

Python prints notes under the traceback; to show them in a UI, read `error.__notes__`.

## Flow files

`compile_file(path)` picks a parser by the file **suffix**. JSON and TOML are built in.

=== "onboarding/pro.toml"

    ```toml
    [[steps]]
    name = "set_plan"
    args = ["pro"]

    [[steps]]
    name = "enable"
    args = ["projects", "invoices", "reports"]

    [[steps]]
    name = "schedule_call"
    kwargs = { days = 3 }
    ```

=== "onboarding/pro.json"

    ```json
    [
      {"name": "set_plan", "args": ["pro"]},
      {"name": "enable", "args": ["projects", "invoices", "reports"]},
      {"name": "schedule_call", "kwargs": {"days": 3}}
    ]
    ```

A TOML flow lists its steps as `[[steps]]` tables; a JSON flow is the list itself.

```python
import json
import tempfile
from pathlib import Path

folder = Path(tempfile.mkdtemp())

(folder / "pro.toml").write_text(
    '[[steps]]\nname = "set_plan"\nargs = ["pro"]\n\n'
    '[[steps]]\nname = "enable"\nargs = ["projects", "invoices", "reports"]\n\n'
    '[[steps]]\nname = "schedule_call"\nkwargs = { days = 3 }\n',
    "utf-8",
)
(folder / "pro.json").write_text(
    json.dumps(
        [
            {"name": "set_plan", "args": ["pro"]},
            {"name": "enable", "args": ["projects", "invoices", "reports"]},
            {"name": "schedule_call", "kwargs": {"days": 3}},
        ]
    ),
    "utf-8",
)

from_toml = compiler.compile_file(folder / "pro.toml")
from_json = compiler.compile_file(folder / "pro.json")

assert from_toml(Customer("a@x.sy")).features == from_json(Customer("b@x.sy")).features == {"projects", "invoices", "reports"}
```

Errors from a file get one more note, `in <path>`, so you know which file to open:

```python
(folder / "broken.toml").write_text('[[steps]]\nname = "set_plan"\n', "utf-8")

try:
    compiler.compile_file(folder / "broken.toml")
except MissingArgumentError as error:
    assert error.__notes__ == ["at $[0]", f"in {folder / 'broken.toml'}"]
```

A file that does not parse raises `InvalidFlowDefinitionError`, and a TOML file without
`[[steps]]` too. `load_flow_definition(path)` returns the parsed data without compiling it.

### Other formats

`register_flow_format(suffix, parser)` adds a format. A parser takes the file text and
returns the list of step dictionaries. With PyYAML:

```py
import yaml

from pyflowstep import register_flow_format

register_flow_format(".yaml", yaml.safe_load)
register_flow_format(".yml", yaml.safe_load)
```

A one-step-per-line format, for quick scripts:

```python
from pyflowstep import UnsupportedFlowFormatError, register_flow_format


def parse_lines(text: str) -> list[dict]:
    steps = []

    for line in text.splitlines():
        if line.strip():
            name, *args = line.split()
            steps.append({"name": name, "args": args})

    return steps


register_flow_format(".flow", parse_lines)

(folder / "trial.flow").write_text("set_plan trial\nsend_email trial_started\n", "utf-8")

assert compiler.compile_file(folder / "trial.flow")(Customer("c@x.sy")).emails == ["trial_started"]

try:
    compiler.compile_file(folder / "trial.xml")
except UnsupportedFlowFormatError as error:
    assert str(error) == "Unsupported flow file format '.xml'. Supported formats: .flow, .json, .toml"
```

Suffixes are case-insensitive and must start with a dot (`ValueError` otherwise).
Registering a suffix again replaces its parser. The registry of formats is global to the
process, so register formats once, at start-up.

## Security

A definition can only use the steps in the mapping you give the compiler. Steps
registered with `hidden=True` are not in `registry.steps`, so JSON cannot reach them, and
`Depends`/`Input` parameters cannot be set from JSON. What a step does with its arguments
is up to you: validate URLs, paths and file names with `Process` when definitions come
from people you do not fully trust.
