# pyflowstep

A lightweight, typed Python library for composing functions into readable, reusable **flows** — a functional replacement for the fluent-interface (method-chaining) pattern, with flows that can be defined, validated and stored as **JSON**.

`pyflowstep` focuses on a functional style:

- steps are plain functions: `(subject, *args, **kwargs) -> subject`
- flows are immutable values that compose with `>>`
- step arguments are validated and parsed when a flow is **built**, not halfway through running it
- raw JSON values become typed arguments with a `Parse` marker next to the parameter
- steps get external objects (a mailer, a database session) through FastAPI-style `Depends`
- the caller hands per-run values to a flow by name: `flow(page, user=user)` fills every `user: User = Input()`
- registry-based registration keeps steps organized and discoverable
- flow definitions can be compiled from dictionaries or JSON
- every registry can describe its flow language as a JSON Schema

It pairs naturally with its siblings [pyspecification](https://github.com/aaltatan/pyspecification) (predicates) and [pyformula](https://github.com/aaltatan/pyformula) (formulas), and has **zero dependencies**.

---

## Why use pyflowstep?

A fluent API makes you put every operation on the class and `return self` from each method:

```python
page.navigate("https://www.google.com").fill("input[name=q]", "pyflowstep").click("#go").wait("#result")
```

That couples *what can be done* to *one class*, you cannot store the chain, reuse half of it, build it from data, or add an operation without editing the class.

With `pyflowstep`, operations are small functions and the chain is a value:

```python
search = navigate("https://www.google.com") >> fill("input[name=q]", "pyflowstep") >> click("#go")

search(page)                      # run it
search >> wait("#result")         # extend it (a new flow, `search` is unchanged)
login >> search >> logout         # combine flows
```

…and the same flow can come from JSON:

```json
[
  {"name": "navigate", "args": ["https://www.google.com"]},
  {"name": "fill", "args": ["input[name=q]", "pyflowstep"]},
  {"name": "click", "kwargs": {"selector": "#go"}}
]
```

---

## Installation

```bash
pip install pyflowstep
```

or with uv:

```bash
uv add pyflowstep
```

Requires Python 3.12+.

---

## Quick start

```python
from typing import Any

from pyflowstep import step


class Page:
    def navigate(self, url: str) -> None:
        print(f"Navigating to {url}")

    def click(self, selector: str) -> None:
        print(f"Clicking on {selector}")

    def fill(self, selector: str, value: Any) -> None:
        print(f"Filling {selector} with {value}")


@step
def navigate(page: Page, url: str) -> Page:
    page.navigate(url)
    return page


@step
def fill(page: Page, selector: str, value: Any) -> Page:
    page.fill(selector, value)
    return page


@step
def click(page: Page, selector: str) -> Page:
    page.click(selector)
    return page


search = navigate("https://www.google.com") >> fill("input[name=q]", 1111) >> click("#go")

print(search)  # Flow(navigate >> fill >> click)
search(Page())
# Navigating to https://www.google.com
# Filling input[name=q] with 1111
# Clicking on #go
```

---

## Core concepts

### Flow

A `Flow[T]` is an immutable sequence of `T -> T` actions. Calling it threads the subject through every action in order.

```python
from pyflowstep import Flow, compose

increment = Flow[int](lambda n: n + 1)
double = Flow[int](lambda n: n * 2)

(increment >> double)(3)            # 8
(double >> increment)(3)            # 7
compose(increment, double)(3)       # 8, same as increment >> double
Flow[int]()(3)                      # 3, an empty flow is the identity
```

- `>>` accepts flows **and** plain callables, on either side: `flow >> fn`, `fn >> flow`.
- Composition flattens: `(a >> b) >> c` and `a >> (b >> c)` have the same three actions.
- Flows support `len()`, iteration, `.actions` and a readable `repr`.

### step

`@step` turns a function whose **first positional parameter is the subject** into a *step factory*. Calling the factory with the remaining arguments returns a single-step flow.

```python
from pyflowstep import step


@step
def add(total: int, amount: int) -> int:
    return total + amount


@step
def multiply(total: int, factor: int) -> int:
    return total * factor


pipeline = add(2) >> multiply(10) >> add(amount=1)
pipeline      # Flow(add >> multiply >> add)
pipeline(1)   # 31
```

`step` and `tap` do one thing: turn a function into a flow factory. Naming a step belongs to the [registry](#registry). Three markers can sit on a parameter: [`Parse`](#parsing-arguments) to convert the value passed for it, [`Depends`](#dependencies) to inject an object nobody passes, and [`Input`](#run-inputs) to receive a value from whoever runs the flow.

Arguments are bound against the function signature **immediately**, so mistakes fail fast:

```python
add()           # MissingArgumentError: missing a required argument: 'amount' for step 'add'
add(1, 2)       # TooManyArgumentsError: too many positional arguments for step 'add'
add(1, x=2)     # UnexpectedKeywordArgumentError: got an unexpected keyword argument 'x' ...
```

### tap

For side-effect steps on a mutable subject, `@tap` ignores the return value and passes the subject on unchanged — no more `return page` boilerplate:

```python
from pyflowstep import tap


@tap
def click(page: Page, selector: str) -> None:
    page.click(selector)
```

---

## Registry

`StepsRegistry[T]` collects named steps for one subject type. It is the vocabulary of your flow language: the compiler and the JSON schema only know about the steps registered in it.

```python
from pyflowstep import StepsRegistry

page_steps = StepsRegistry[Page]()


@page_steps.tap()
def navigate(page: Page, url: str) -> None:
    """Open a url in the page."""
    page.navigate(url)


@page_steps.tap()
def click(page: Page, selector: str) -> None:
    """Click the element matching a CSS selector."""
    page.click(selector)


@page_steps.tap(name="type")
def fill(page: Page, selector: str, value: str) -> None:
    """Type a value into a field."""
    page.fill(selector, value)


@page_steps.tap(hidden=True)
def debug_dump(page: Page) -> None:
    """Python-only helper, never exposed to JSON."""


page_steps["click"]("#go")        # look up a step factory by name
"type" in page_steps              # True
list(page_steps.steps)            # ['navigate', 'click', 'type']  (hidden steps are excluded)

page_steps.register(lambda page: page, name="noop")  # register without a decorator
```

| Method / attribute                                               | Description                                                 |
| ---------------------------------------------------------------- | ----------------------------------------------------------- |
| `step(name=, description=, hidden=)`                             | Decorator for `(subject, ...) -> subject` functions         |
| `tap(name=, description=, hidden=)`                              | Decorator for side-effect functions (return value ignored)  |
| `register(fn, *, name=, description=, hidden=, passthrough=)`    | Register without decorator syntax                           |
| `steps`                                                          | Read-only mapping of visible steps                          |
| `registry[name]`, `name in registry`, `len()`, iteration         | Lookup over visible steps                                   |

- `name` is the step's public name: the compiler looks it up, and `repr` and argument errors show it (`Flow(type)` above, not `Flow(fill)`).
- `description` overrides the docstring, which becomes the step description in the JSON schema.

---

## Parsing arguments

Flows often come from JSON or a web form, where every value arrives as a string, number, boolean, list, object or null, while your steps want dates, decimals, enums, clean text or loaded data. Mark the parameter with `Parse(fn)` inside `Annotated`, and `fn` is applied to the value that is passed for it:

```python
from typing import Annotated

from pyflowstep import Parse


@page_steps.tap()
def wait(page: Page, selector: str, timeout: Annotated[float, Parse(float)] = 5.0) -> None:
    page.wait(selector, timeout)


wait("#result", "10")   # timeout is 10.0
```

```json
{"name": "wait", "args": ["#result", "10"]}
```

The marker sits next to the parameter it changes, and it works with the plain `@step` and `@tap` decorators too; no registry is required.

### Name it once, reuse it

A `type` alias gives a parsed type a name, so many steps can share it:

```python
from decimal import Decimal

type Money = Annotated[Decimal, Parse(Decimal)]
type Text = Annotated[str, Parse(str.strip), Parse(str.lower)]   # several parsers run left to right


@catalog_steps.step()
def price_between(products: Catalog, low: Money, high: Money) -> Catalog: ...


@catalog_steps.step()
def search(products: Catalog, text: Text, min_stars: Annotated[float, Parse(float)] = 0) -> Catalog: ...
```

### Loading data from a value in the JSON

A parser can be any function of one value, so the JSON can send a path and the step can receive what was loaded from it:

```python
def load_names(path: str) -> frozenset[str]:
    return frozenset(Path(path).read_text().splitlines())


type Names = Annotated[frozenset[str], Parse(load_names)]


@catalog_steps.step()
def exclude(products: Catalog, names: Names) -> Catalog:
    return tuple(product for product in products if product.name not in names)
```

```json
{"name": "exclude", "args": ["discontinued.txt"]}
```

The file is read **once, when the flow is built**. Every run of that flow reuses the loaded names. For an object that must be fresh on every run, or that the JSON must not choose at all, use a [dependency](#dependencies) instead.

### `*args` and `**kwargs`

On `*args` the parser applies to each item, and on `**kwargs` to each value:

```python
@barista.step()
def top_with(drink: Drink, *toppings: Text) -> Drink: ...


@catalog_steps.step()
def where(products: Catalog, *, in_stock: Annotated[bool, Parse(parse_bool)] = False, **fields: Text) -> Catalog: ...


where(in_stock="yes", brand=" SONIC ")   # in_stock=True, brand="sonic"
```

### Which values are parsed, and when

- Only values that are **actually passed**, positionally or by keyword. Default values are never parsed.
- Parsing runs **once per factory call**, while the flow is being built, not every time the flow runs.
- Arguments are checked against the step's signature first, so a missing or extra argument is reported as an `ArgumentError` before any parser runs.

```python
flow = add_syrup("  Vanilla ", "2")   # parsed here: flavor="vanilla", pumps=2
flow(drink)                           # the step runs with the parsed values
flow(another_drink)                   # nothing is parsed again
```

### Errors

A parser that fails on a value raises `ParseArgumentError`, chained to the original exception. Inside a compiled flow it also carries the JSON path of the step, so a bad value is found before anything runs:

```text
pyflowstep.exceptions.ParseArgumentError: Argument 'limit' with value 'two' failed to parse, invalid literal for int() with base 10: 'two'
at $[1]
```

A marker that cannot work raises `InvalidParserError` when the step is created:

| Problem                                              | Example                                              |
| ---------------------------------------------------- | ---------------------------------------------------- |
| The parser is not callable                           | `Parse("int")`                                       |
| The marker is used as a default value                | `amount: int = Parse(int)`, write `Annotated[int, Parse(int)]` |
| The marker is on the subject (the first parameter)   | `def step(page: Annotated[Page, Parse(...)], ...)`   |
| One parameter has both `Parse` and `Depends`         | nothing is passed for a dependency, so there is nothing to parse |

### In the JSON schema

A parsed parameter is described by **what the JSON must send**. The schema takes it from the type hint of the parser's own parameter (`load_names(path: str)` means `string`). If the parser has no type hint, as with `int`, `Decimal` or an enum class, the schema falls back to the parameter's type.

| Parameter                                    | Schema                          |
| -------------------------------------------- | ------------------------------- |
| `names: Annotated[frozenset[str], Parse(load_names)]` | `{"type": "string"}`   |
| `limit: Annotated[int, Parse(int)]`          | `{"type": "integer"}`           |
| `kind: Annotated[Milk, Parse(Milk)]`         | `{"enum": ["whole", "oat", "almond"], "type": "string"}` |

### Upgrading from 0.1

The `processors=` option of the registry is gone. Move each entry onto its parameter:

| 0.1                                               | 0.2                                                     |
| ------------------------------------------------- | ------------------------------------------------------- |
| `processors={"timeout": float}`                   | `timeout: Annotated[float, Parse(float)]`               |
| `processors=normalize` (every argument)           | annotate each parameter, usually with a shared alias such as `Text` |
| `processors={"pumps": int, ...: normalize}`       | `pumps: Annotated[int, Parse(int)]`, the others `Text`  |
| `...` covering `**kwargs`                         | `**fields: Text`                                        |
| `ProcessArgumentError`                            | `ParseArgumentError`                                    |
| `InvalidProcessorsError`                          | removed; a key can no longer be misspelled              |

See [`examples/parsing.py`](examples/parsing.py) for every form working together on data from a web form.

---

## Dependencies

Some steps need objects that cannot be written in JSON: a mailer, a database session, an API client. Mark the parameter with `Depends(provider)` and it stops being an argument. Nobody passes it, neither Python nor JSON; `provider` is called to produce it when the flow runs.

```python
from pyflowstep import Depends, StepsRegistry

steps = StepsRegistry[Order]()


def get_mailer() -> Mailer:
    return Mailer("smtp.example.com")


@steps.tap()
def send_email(order: Order, template: str, mailer: Mailer = Depends(get_mailer)) -> None:
    mailer.send(order.customer, template)


send_email("receipt")   # only `template` is an argument
```

```json
[{"name": "send_email", "args": ["receipt"]}]
```

It works the same with the plain `@step` and `@tap` decorators; no registry is required.

### Always the default value

`Depends(...)` is written as the default value of the parameter, in steps and in providers. To name a dependency once and reuse it in many steps, keep the marker in a constant:

```python
# inline: quick, for a one-off
def send_email(order: Order, template: str, mailer: Mailer = Depends(get_mailer)) -> None: ...


# a constant: name the dependency once, reuse it
MAILER = Depends(get_mailer)

def send_email(order: Order, template: str, mailer: Mailer = MAILER) -> None: ...
def send_invoice(order: Order, mailer: Mailer = MAILER) -> None: ...
```

It is never written inside `Annotated`. Only a default value tells a type checker that the parameter is not passed, so `send_email("receipt")` type-checks; `Annotated[Mailer, Depends(get_mailer)]` raises `InvalidDependencyError` when the step is created.

### One object per flow run

A flow run is one scope, like one request in a web framework. A provider is called **at most once per run**, and every step of that run receives the same object. The next run starts fresh.

A provider written as a generator is cleaned up when the run ends. If a step fails, the error is raised inside the provider at its `yield`, so it can roll back:

```python
from collections.abc import Iterator


def get_session() -> Iterator[Session]:
    session = Session()
    try:
        yield session          # shared by every step of this run
    except Exception:
        session.rollback()     # a step failed
        raise
    else:
        session.commit()       # the whole flow succeeded
    finally:
        session.close()


SESSION = Depends(get_session)


@steps.tap()
def save(order: Order, session: Session = SESSION) -> None:
    session.add(order)


@steps.tap()
def audit(order: Order, action: str, session: Session = SESSION) -> None:
    session.add(AuditRow(order.id, action))   # the same session `save` used


flow = save() >> audit("fulfilled")

flow(order_1)   # session A: opened, used twice, committed, closed
flow(order_2)   # session B
```

Cleanups run in reverse order, and a provider cannot swallow a step's error: it is always re-raised. Flows nested inside a flow, or called from inside a step, join the run that is already open.

### Sub-dependencies

A provider's own parameters can use `Depends` too:

```python
def get_settings() -> Settings:
    return Settings()


def get_mailer(settings: Settings = Depends(get_settings)) -> Mailer:
    return Mailer(settings.smtp_host)
```

Any other provider parameter must have a default. A provider can be any callable: a function, a class, a `functools.partial`, or an object with `__call__`.

### Replacing a dependency in tests

```python
from pyflowstep import override_dependencies

with override_dependencies({get_mailer: FakeMailer}):
    flow(order)          # every step that asked for get_mailer gets a FakeMailer

flow(order)              # the real mailer again
```

Keys are the original providers and values the providers to call instead. Nested blocks add up, and everything is restored when the block exits, even after an error.

### Rules

- **Invisible to JSON.** A dependency is absent from the JSON schema, cannot be parsed, and passing one raises `UnexpectedKeywordArgumentError` (or `TooManyArgumentsError`) when the flow is built.
- **Declarations are checked early**, when the step is created, with `InvalidDependencyError`: a provider that is not callable, is circular, or has a required parameter that is not a dependency; a dependency on the subject or on a positional-only parameter; `Depends` written inside `Annotated`.
- **Providers run late**, when the flow runs. An error inside a provider surfaces then, not at compile time.
- A dependency is for an object the JSON must **not** choose. When the JSON should pick one by name (`"via": "email"`), use [`Parse`](#parsing-arguments) with a function that turns the name into the object.

Using ruff? Its `B008` rule flags function calls in argument defaults. Tell it `Depends` is a marker:

```toml
[tool.ruff.lint.flake8-bugbear]
extend-immutable-calls = ["pyflowstep.Depends"]
```

See [`examples/dependencies.py`](examples/dependencies.py) for a complete flow with a mailer, a per-run session and a test override.

### Upgrading from 0.4

`Annotated[T, Depends(provider)]` is gone, for the same reason `Input[T]` went in 0.4: a type checker reported `send_email("receipt")` as missing its `mailer` argument. Move the marker to the default value, in steps and in providers:

| 0.4                                                       | 0.5                                          |
| --------------------------------------------------------- | -------------------------------------------- |
| `mailer: Annotated[Mailer, Depends(get_mailer)]`          | `mailer: Mailer = Depends(get_mailer)`       |
| `type MailerDep = Annotated[Mailer, Depends(get_mailer)]` | `MAILER = Depends(get_mailer)`               |
| `mailer: MailerDep`                                       | `mailer: Mailer = MAILER`                    |

---

## Run inputs

Some values exist only where the flow is run: the logged-in user, the record being processed, credentials read from a prompt. No provider can build them and JSON must not hold them. Give the parameter the default `Input()` and the caller supplies it, by name, when it runs the flow:

```python
from pyflowstep import Input, StepsRegistry

steps = StepsRegistry[Page]()


@steps.tap()
def login(page: Page, url: str, credentials: Credentials = Input()) -> None:
    page.navigate(url)
    page.fill("#user", credentials.username)
    page.fill("#password", credentials.password)


@steps.tap()
def fill_year(page: Page, selector: str, voucher: Voucher = Input()) -> None:
    page.fill(selector, voucher.year)


flow = login("https://example.com/login") >> fill_year("#year")   # inputs are not arguments

flow(page, credentials=credentials, voucher=voucher)              # they are given to the run
```

```json
[
  {"name": "login", "args": ["https://example.com/login"]},
  {"name": "fill_year", "args": ["#year"]}
]
```

The name of the input is the name of the parameter, and every step that declares it receives the same value.

`Input()` is written as the default value, never inside `Annotated`, so that type checkers see the parameter as optional and accept `fill_year("#year")`.

### Checked before anything runs

A flow knows the inputs its steps require, and checks them before the first step runs. A forgotten input never fails halfway through:

```python
flow.inputs   # frozenset({'credentials', 'voucher'})

flow(page, credentials=credentials)
# MissingInputError: missing run input 'voucher' for step 'fill_year'; run the flow as flow(subject, voucher=...)
```

### Rules

- **Invisible to JSON**, like a dependency: an input is absent from the JSON schema, cannot be parsed, and passing one while building the flow raises `UnexpectedKeywordArgumentError` (or `TooManyArgumentsError`).
- **`Input(default=...)` makes the input optional**: with `note: str = Input(default="")`, `""` is used when the caller passes no `note`. Optional inputs are not listed in `flow.inputs`.
- **Extra inputs are ignored**, so one caller can run different flows, each using the inputs it needs.
- **Nested flows see the inputs of the run they join.** A flow called from inside a step can be given inputs of its own, `inner(page, voucher=other)`; they are laid over the outer ones for that call only.
- **Declarations are checked early**, when the step is created, with `InvalidInputError`: an input on the subject, on a positional-only parameter, or written inside `Annotated`. A provider cannot take an input.

Using ruff? Add `Input` next to `Depends` for its `B008` rule:

```toml
[tool.ruff.lint.flake8-bugbear]
extend-immutable-calls = ["pyflowstep.Depends", "pyflowstep.Input"]
```

### Upgrading from 0.3

`Input[T]` is gone, because a type checker reported `fill_year("#year")` as missing its `voucher` argument. Move the marker to the default value:

| 0.3                                | 0.4                                      |
| ---------------------------------- | ---------------------------------------- |
| `voucher: Input[Voucher]`          | `voucher: Voucher = Input()`             |
| `note: Input[str] = ""`            | `note: str = Input(default="")`          |

### `Input` or `Depends`?

| The object…                                                  | Use                                   |
| ------------------------------------------------------------ | ------------------------------------- |
| is written in the flow definition (a selector, a limit)      | a plain argument, with `Parse` if needed |
| can be built by a function, the same way for every caller (a mailer, a session) | `Depends(provider)`     |
| is only known to whoever runs the flow (a user, a record, credentials) | `Input()`                   |

---

## Compiling flows from JSON

`FlowCompiler` turns a flow definition — a list of step dictionaries — into a `Flow`.

```python
from pyflowstep import FlowCompiler

compiler = FlowCompiler(page_steps.steps)

login = compiler.compile(
    [
        {"name": "navigate", "args": ["https://example.com/login"]},
        {"name": "type", "args": ["#email", "ada@example.com"]},
        {"name": "click", "kwargs": {"selector": "button[type=submit]"}},
    ],
)

login(Page())
```

The compiler takes already-parsed data. Reading JSON, YAML, a database row or an API payload is up to you:

```python
import json
from pathlib import Path

login = compiler.compile(json.loads(Path("login.json").read_text()))
```

Each step dictionary has this shape — only `name` is required:

```json
{"name": "fill", "args": ["#email"], "kwargs": {"value": "ada@example.com"}}
```

Everything is validated while compiling, before any step runs. Errors carry a note with their JSON path:

```text
pyflowstep.exceptions.ParseArgumentError: Argument 'url' with value 'http://insecure.example.com' failed to parse, only https urls are allowed
at $[1]
```

| Problem                                          | Exception                                              |
| ------------------------------------------------ | ------------------------------------------------------ |
| Not a list / malformed step dict                 | `InvalidFlowDefinitionError`                           |
| Unknown or hidden step name                      | `StepDoesNotExistError` (lists the available steps)    |
| Missing / extra / duplicated arguments           | `MissingArgumentError`, `TooManyArgumentsError`, ...   |
| A parser rejects a value                         | `ParseArgumentError`                                   |

A compiled flow is an ordinary `Flow`, so it composes with Python steps: `login >> click("#profile")`.

---

## JSON Schema

Describe your flow language so a UI, a validator, or an LLM can produce valid flows:

```python
import json

from pyflowstep import get_flow_json_schema, get_step_json_schema

print(json.dumps(get_flow_json_schema(page_steps.steps), indent=2))
```

Output, trimmed to the `click` step:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "array",
  "items": {
    "oneOf": [
      {
        "type": "object",
        "properties": {
          "name": {"const": "click"},
          "args": {"type": "array", "prefixItems": [{"type": "string"}], "items": false},
          "kwargs": {
            "type": "object",
            "properties": {"selector": {"type": "string"}},
            "required": [],
            "additionalProperties": false
          }
        },
        "required": ["name"],
        "additionalProperties": false,
        "description": "Click the element matching a CSS selector."
      }
    ]
  }
}
```

Supported annotations: `str`, `int`, `float`, `bool`, `None`, `Decimal`, `datetime`, `date`, `time`, `UUID`, `list`/`tuple`/`set`/`frozenset`, `dict`, `Literal`, `Enum`, unions, `Annotated`, `TypedDict`, and `type` aliases. Anything else maps to `{}` (any value). JSON-compatible default values are included as `default`.

---

## Examples

Runnable examples live in [`examples/`](examples):

- [`examples/browser.py`](examples/browser.py) — the `Page` automation above: `tap` steps, an https-only parser, reusable sub-flows and a JSON login scenario.

  ```bash
  uv run python -m examples.browser
  ```

- [`examples/coffee.py`](examples/coffee.py) — a coffee shop where every step returns a **new** immutable `Drink`. The menu is JSON, orders are customized with Python steps, and a hidden staff-only `discount` step is invisible to the menu.

  ```bash
  uv run python -m examples.coffee
  ```

  ```python
  order("latte", size("L"), add_syrup("vanilla")).describe()
  # 'L espresso, 1 shot(s), 200ml whole milk, 1x vanilla syrup -> $3.65'
  ```

- [`examples/parsing.py`](examples/parsing.py) — every way to use `Parse`, side by side. Shop filters arrive from a web form as raw strings (`"4"`, `"yes"`, `" SONIC "`, a file path) and are turned into typed, clean arguments, including a set of names loaded from that path:

  ```bash
  uv run python -m examples.parsing
  ```

  ```python
  type Text = Annotated[str, Parse(str.strip), Parse(str.lower)]
  type Names = Annotated[frozenset[str], Parse(load_names)]

  @catalog_steps.step()
  def where(products: Catalog, *, in_stock: Annotated[bool, Parse(parse_bool)] = False, **fields: Text) -> Catalog: ...

  @catalog_steps.step()
  def exclude(products: Catalog, names: Names) -> Catalog: ...
  ```

- [`examples/dependencies.py`](examples/dependencies.py) — steps that need objects JSON cannot describe. A fulfilment flow stored as JSON uses a mailer (with a sub-dependency) and a database session that is opened once per run, shared by two steps, then committed or rolled back. Also shows swapping the mailer for a fake in a test:

  ```bash
  uv run python -m examples.dependencies
  ```

  ```python
  @fulfilment_steps.tap()
  def send_email(order: Order, template: str, mailer: Mailer = Depends(get_mailer)) -> None: ...

  @fulfilment_steps.tap()
  def save(order: Order, session: Session = SESSION) -> None: ...
  ```

### Working with pyspecification and pyformula

Predicates and formulas are just callables, so they plug straight into steps:

```python
from dataclasses import dataclass, replace
from decimal import Decimal

from pyformula import variable
from pyspecification import object_rule
from pyflowstep import step


@dataclass(frozen=True)
class Invoice:
    subtotal: Decimal
    tax: Decimal = Decimal(0)
    notes: tuple[str, ...] = ()


@object_rule()
def is_large(invoice: Invoice, limit: Decimal) -> bool:
    return invoice.subtotal >= limit


@variable()
def subtotal(invoice: Invoice) -> Decimal:
    return invoice.subtotal


@step
def note_if(invoice: Invoice, rule, note: str) -> Invoice:
    return replace(invoice, notes=(*invoice.notes, note)) if rule(invoice) else invoice


@step
def apply_tax(invoice: Invoice, formula) -> Invoice:
    return replace(invoice, tax=Decimal(str(formula(invoice))))


checkout = note_if(is_large(Decimal(100)), "needs approval") >> apply_tax(round(subtotal * 0.15, 2))
```

---

## API reference

| Name                                                         | Kind      | Description                                                     |
| ------------------------------------------------------------ | --------- | --------------------------------------------------------------- |
| `Flow[T]`                                                    | class     | Immutable, callable sequence of actions; composes with `>>`     |
| `compose(*actions)`                                          | function  | Combine actions and flows into one flat flow                    |
| `step` / `tap`                                               | decorator | Turn a function into a step factory                             |
| `StepsRegistry[T]`                                           | class     | Named collection of steps                                       |
| `Parse(fn)`                                                  | marker    | Apply `fn` to the value passed for a parameter, see [Parsing arguments](#parsing-arguments) |
| `Depends(provider)`                                          | marker    | Inject a parameter by calling `provider`, see [Dependencies](#dependencies) |
| `override_dependencies(mapping)`                             | context manager | Replace providers inside a `with` block, for tests        |
| `Input(default=...)`                                         | marker    | Receive a parameter from the caller of the flow, `flow(subject, name=value)`, see [Run inputs](#run-inputs) |
| `Flow.inputs`                                                | property  | The names of the inputs a flow requires                         |
| `FlowCompiler[T](steps)`                                     | class     | `compile(definition)` turns parsed step dicts into a flow       |
| `validate_step_dict(item, path)`                             | function  | Validate one step dictionary                                    |
| `get_json_schema(annotation)`                                | function  | JSON Schema of a type annotation                                |
| `get_step_json_schema(name, step)`                           | function  | JSON Schema of one step dictionary                              |
| `get_flow_json_schema(steps)`                                | function  | JSON Schema of a whole flow definition                          |

All exceptions derive from `PyflowstepError`; argument errors, `InvalidParserError`, `InvalidDependencyError`, `InvalidInputError` and `MissingInputError` also derive from `TypeError`, definition errors from `ValueError`, and `StepDoesNotExistError` from `LookupError`.

---

## Development

```bash
uv sync
uv run pytest --cov --cov-report term-missing
```

The test suite also runs every docstring example (`--doctest-modules`).

## License

GPL-3.0
