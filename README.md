# pyflowstep

A lightweight, typed Python library for composing functions into readable, reusable **flows** — a functional replacement for the fluent-interface (method-chaining) pattern, with flows that can be defined, validated and stored as **JSON**.

`pyflowstep` focuses on a functional style:

- steps are plain functions: `(subject, *args, **kwargs) -> subject`
- flows are immutable values that compose with `>>`
- step arguments are validated and processed when a flow is **built**, not halfway through running it
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

`step` and `tap` do one thing: turn a function into a flow factory. Naming a step and processing its arguments belong to the [registry](#registry).

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


@page_steps.tap(name="type", processors={"value": str})
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
| `step(name=, description=, processors=, hidden=)`                | Decorator for `(subject, ...) -> subject` functions         |
| `tap(name=, description=, processors=, hidden=)`                 | Decorator for side-effect functions (return value ignored)  |
| `register(fn, *, name=, description=, processors=, hidden=, passthrough=)` | Register without decorator syntax                 |
| `steps`                                                          | Read-only mapping of visible steps                          |
| `registry[name]`, `name in registry`, `len()`, iteration         | Lookup over visible steps                                   |

- `name` is the step's public name: the compiler looks it up, and `repr` and argument errors show it (`Flow(type)` above, not `Flow(fill)`).
- `processors` transform the raw arguments every time the factory is called, before they reach the step. See [Processors](#processors).
- `description` overrides the docstring, which becomes the step description in the JSON schema.

---

## Processors

Processors transform raw arguments before a step is built. They matter most for JSON and web forms, where every value arrives as a string, number, boolean, list, object or null, while your steps want dates, decimals, enums and clean text.

Processors are a registry option: pass `processors=` to `registry.step()`, `registry.tap()` or `registry.register()`.

### The four forms

| `processors=`                              | Effect                                                         |
| ------------------------------------------ | -------------------------------------------------------------- |
| *(omitted, `None`)*                        | Arguments reach the step exactly as given                      |
| `fn`                                       | `fn` is applied to **every** argument                          |
| `{"name": fn, ...}`                        | Only the named arguments are processed, the rest are untouched |
| `{"name": fn, ...: other}`                 | The named arguments use their own processor, `...` covers **all the others** |

```python
from decimal import Decimal


@page_steps.tap()                                          # nothing to process
def click(page: Page, selector: str) -> None: ...


@barista.step(processors=Decimal)                          # every argument
def price_between(drink: Drink, low: Decimal, high: Decimal) -> Drink: ...


@page_steps.tap(processors={"timeout": float})             # only `timeout`, `selector` untouched
def wait(page: Page, selector: str, timeout: float = 5.0) -> None: ...


@barista.step(processors={"pumps": int, ...: str.strip})   # `pumps`, and `...` for the rest
def add_syrup(drink: Drink, flavor: str, pumps: int = 1) -> Drink: ...
```

### The `...` key

`...` (Python's `Ellipsis`) reads as "every argument not named here", just like in `tuple[int, ...]`. A named entry always wins over `...`, and a mapping holding only `...` behaves like a single callable. Because `...` can never be a parameter name, it can never clash with one.

It also covers the extra keywords a step collects with `**kwargs`, which is handy for open-ended filters:

```python
def normalize(text: str) -> str:
    return text.strip().lower()


@catalog_steps.step(processors={"in_stock": parse_bool, ...: normalize})
def where(products: Catalog, *, in_stock: bool = False, **fields: str) -> Catalog: ...


where(in_stock="yes", brand=" SONIC ")   # in_stock=True, brand="sonic"
```

### Which values are processed

- A processor for a parameter applies whether the value was passed positionally **or** by keyword.
- For `*args` it applies to each item. For `**kwargs`, each extra keyword is looked up by its own name, falling back to `...`.
- Default values are never processed: only arguments that were actually passed go through a processor.
- The subject (the step's first parameter) is never processed, since it is not a step argument.

### When they run

Processors run **once per factory call**, while the flow is being built, not every time the flow runs:

```python
flow = add_syrup("  Vanilla ", "2")   # processors run here: flavor="Vanilla", pumps=2
flow(drink)                           # the step runs with the processed values
flow(another_drink)                   # no processing again
```

The arguments are first bound to the step signature, so a missing or extra argument is reported as an `ArgumentError` before any processor runs.

### Errors

Mistakes in the `processors` option are caught **when the step is registered**, with `InvalidProcessorsError`:

```python
@page_steps.tap(processors={"timout": float})   # typo
def wait(page: Page, selector: str, timeout: float = 5.0) -> None: ...
# InvalidProcessorsError: Processors of step 'wait' name unknown parameters ['timout'], available parameters: selector, timeout
```

| Problem                                        | Message                                                          |
| ---------------------------------------------- | ---------------------------------------------------------------- |
| A key is not a parameter of the step           | `... name unknown parameters ['timout'], available parameters: ...` |
| A value is not callable, e.g. `{"pumps": "int"}` | `... must be callables, not for ['pumps']`                       |
| Neither a callable nor a mapping               | `... must be a callable or a mapping of parameter names to callables, got ...` |

Steps that accept `**kwargs` allow any key, since any keyword name is valid for them.

A processor that fails on a value raises `ProcessArgumentError`, chained to the original exception. Inside a compiled flow it also carries the JSON path of the step:

```text
pyflowstep.exceptions.ProcessArgumentError: Argument 'price' with value 'cheap' failed to process, [<class 'decimal.ConversionSyntax'>]
at $[0]
```

See [`examples/processors.py`](examples/processors.py) for every form working together on data from a web form.

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
pyflowstep.exceptions.ProcessArgumentError: Argument 'url' with value 'http://insecure.example.com' failed to process, only https urls are allowed
at $[1]
```

| Problem                                          | Exception                                              |
| ------------------------------------------------ | ------------------------------------------------------ |
| Not a list / malformed step dict                 | `InvalidFlowDefinitionError`                           |
| Unknown or hidden step name                      | `StepDoesNotExistError` (lists the available steps)    |
| Missing / extra / duplicated arguments           | `MissingArgumentError`, `TooManyArgumentsError`, ...   |
| A processor rejects a value                      | `ProcessArgumentError`                                 |

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

- [`examples/browser.py`](examples/browser.py) — the `Page` automation above: `tap` steps, an https-only processor, reusable sub-flows and a JSON login scenario.

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

- [`examples/processors.py`](examples/processors.py) — every `processors` form side by side, including `...` for "all other arguments" and for `**kwargs`. Shop filters arrive from a web form as raw strings (`"4"`, `"yes"`, `" SONIC "`) and are turned into typed, clean arguments:

  ```bash
  uv run python -m examples.processors
  ```

  ```python
  @catalog_steps.step(processors={"min_stars": float, ...: normalize})
  def search(products: Catalog, text: str, min_stars: float = 0) -> Catalog: ...

  @catalog_steps.step(processors={"in_stock": parse_bool, ...: normalize})
  def where(products: Catalog, *, in_stock: bool = False, **fields: str) -> Catalog: ...
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
| `Processors`                                                 | type      | `Callable \| Mapping[str \| EllipsisType, Callable]`, see [Processors](#processors) |
| `FlowCompiler[T](steps)`                                     | class     | `compile(definition)` turns parsed step dicts into a flow       |
| `validate_step_dict(item, path)`                             | function  | Validate one step dictionary                                    |
| `get_json_schema(annotation)`                                | function  | JSON Schema of a type annotation                                |
| `get_step_json_schema(name, step)`                           | function  | JSON Schema of one step dictionary                              |
| `get_flow_json_schema(steps)`                                | function  | JSON Schema of a whole flow definition                          |

All exceptions derive from `PyflowstepError`; argument errors and `InvalidProcessorsError` also derive from `TypeError`, definition errors from `ValueError`, and `StepDoesNotExistError` from `LookupError`.

---

## Development

```bash
uv sync
uv run pytest --cov --cov-report term-missing
```

The test suite also runs every docstring example (`--doctest-modules`).

## License

GPL-3.0
