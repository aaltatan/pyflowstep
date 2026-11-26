# Registries

A `StepsRegistry[T]` is the **vocabulary of a flow language** for subjects of type `T`:
the steps a [compiler](compiling.md) understands and a [JSON Schema](json-schema.md)
describes. It gives you lookup by name, one place to register every step, and protection
against two steps with the same name.

## Example: a QA team's browser vocabulary

A QA team writes end-to-end test scenarios as JSON. The developers provide the steps.
(The `Page` below records what it is asked to do; in real life it wraps Playwright or
Selenium.)

```python
from pyflowstep import StepsRegistry


class Page:
    def __init__(self) -> None:
        self.url = ""
        self.actions: list[str] = []
        self.fields: dict[str, str] = {}


browser = StepsRegistry[Page]()


@browser.step()
def navigate(page: Page, url: str) -> Page:
    """Open a URL."""
    page.url = url
    page.actions.append(f"open {url}")
    return page


@browser.tap()
def fill(page: Page, selector: str, value: str) -> None:
    """Type a value into a field."""
    page.fields[selector] = value
    page.actions.append(f"fill {selector}")


@browser.tap(name="click", description="Click an element.")
def click_element(page: Page, selector: str) -> None:
    page.actions.append(f"click {selector}")


login = browser["navigate"]("https://shop.example/login") >> fill("#email", "qa@shop.example") >> browser["click"]("#submit")

page = login(Page())

assert page.actions == ["open https://shop.example/login", "fill #email", "click #submit"]
assert repr(login) == "Flow(navigate >> fill >> click)"
```

The decorators also **return** the factory, so `fill(...)` and `browser["fill"](...)` are
the same. Use the name lookup when the name comes from data.

## Registering

| Method | Registers |
| --- | --- |
| `@registry.step(*, name=None, description=None, hidden=False)` | a step, like [`@step`](steps.md) |
| `@registry.tap(*, name=None, description=None, hidden=False)` | a tap, like [`@tap`](steps.md#tap) |
| `@registry.output(input_name, /, *, step_name=None, description=None, hidden=False)` | an [output](inputs.md#outputs) step |
| `@registry.override(original, /, *, name=None, description=None, hidden=False)` | a [variant](variants-and-chains.md#variants-with-override) of a step |
| `@registry.chain(*, name=None, description=None, hidden=False)` | a [chain](variants-and-chains.md#chains) |
| `registry.register(fn, /, *, name=None, description=None, hidden=False, passthrough=False)` | an existing function; `passthrough=True` makes it a tap |

Every one returns the step factory.

- `name` is the lookup key **and** the name shown in `repr` and error messages. It
  defaults to the function name.
- `description` replaces the docstring, which is what the JSON Schema shows.
- `hidden` keeps the step out of lookups, see [below](#hidden-steps).

### Functions you did not write

`register` adds an existing function, for example from a helper module, without
decorating it at its definition. A lambda needs a `name`:

```python
def scroll_to_bottom(page: Page) -> Page:
    page.actions.append("scroll")
    return page


browser.register(scroll_to_bottom)
browser.register(lambda page: page.actions.append("screenshot"), name="screenshot", passthrough=True)

shot = (browser["scroll_to_bottom"]() >> browser["screenshot"]())(Page())

assert shot.actions == ["scroll", "screenshot"]
```

Register the **plain** function: a factory made with `@step` cannot be registered again
(it raises `InvalidStepError`). Decorate with the registry method instead of `@step` when
a step belongs in a registry.

## Looking up

| Member | Returns |
| --- | --- |
| `registry[name]` | the factory; `StepDoesNotExistError` if unknown or hidden |
| `name in registry` | whether a visible step has that name |
| `iter(registry)`, `len(registry)` | the visible names, their count |
| `registry.steps` | a read-only mapping of the visible steps, for the compiler and the schema |

```python
assert "click" in browser
assert "click_element" not in browser  # registered under its name
assert list(browser) == ["navigate", "fill", "click", "scroll_to_bottom", "screenshot"]
assert browser["fill"].__doc__ == "Type a value into a field."
assert browser["click"].__doc__ == "Click an element."
```

`registry.steps` is a snapshot taken when you read it: read it again after registering
more steps.

## Errors

An unknown name lists what exists, sorted:

```python
from pyflowstep import InvalidStepNameError, StepAlreadyRegisteredError, StepDoesNotExistError

try:
    browser["type"]
except StepDoesNotExistError as error:
    assert str(error) == "Step 'type' does not exist. Available steps: click, fill, navigate, screenshot, scroll_to_bottom"
```

A taken name (hidden ones included) raises `StepAlreadyRegisteredError`, and a name that
is not an ASCII Python identifier raises `InvalidStepNameError` (also a `ValueError`):

```python
try:
    browser.register(scroll_to_bottom, name="click")
except StepAlreadyRegisteredError as error:
    assert str(error) == "Step 'click' is already registered."

try:
    browser.register(scroll_to_bottom, name="scroll-down")
except InvalidStepNameError as error:
    assert str(error).startswith("Invalid step name: 'scroll-down'")
```

A failed registration leaves the registry unchanged.

## Hidden steps

A hidden step is registered (its name is taken) but invisible: not in `steps`, not in
`in`, `iter` or `len`, and `registry[name]` does not find it. So it is **not** available
to JSON flows or in the schema. The factory returned by the decorator still works in
Python.

Use it for steps that are fine in code but must not be offered to the people who write
flows, such as a step that bypasses the login screen in tests:

```python
@browser.step(hidden=True)
def inject_session_cookie(page: Page, token: str) -> Page:
    page.actions.append("cookie")
    return page


assert "inject_session_cookie" not in browser
assert inject_session_cookie("secret")(Page()).actions == ["cookie"]
```

## One subject type per registry

A registry is typed by its subject: `StepsRegistry[Page]`, `StepsRegistry[Order]`. Keep
one registry per subject type, and per audience if two teams should see different
vocabularies: nothing stops a function from being registered in two registries.
