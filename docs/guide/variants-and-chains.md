# Variants and chains

Two ways to build bigger steps from the ones you have:

- **`override`**: the **same** step with other defaults, for example one parameter
  becoming a run input.
- **`chain`**: a **named group** of steps, with arguments, usable like one step.

The examples share a small payroll portal (`Page` records what it is asked to do):

```python
from dataclasses import dataclass
from datetime import date
from typing import Annotated

from pyargprocessors import Process

from pyflowstep import Flow, Input, StepsRegistry, chain, override, step, tap


class Page:
    def __init__(self) -> None:
        self.log: list[str] = []


portal = StepsRegistry[Page]()


@portal.tap()
def fill_date(page: Page, selector: str, *, value: Annotated[date, Process(date.fromisoformat)]) -> None:
    """Type a date into a date field."""
    page.log.append(f"{selector}={value.isoformat()}")


@portal.tap()
def click(page: Page, selector: str) -> None:
    page.log.append(f"click {selector}")
```

## Variants with `override`

The payroll clerk's script fills the period of each payroll run. The dates differ per
run, so they should be [run inputs](inputs.md), but `fill_date` takes them as arguments.
Rather than copy its body, declare a **variant**:

```python
@override(fill_date)
def fill_period_start(page: Page, selector: str, *, value: date = Input()) -> None:
    """Fill the start of the payroll period from the run."""


period = fill_period_start("#from") >> click("#load")

page = period(Page(), value=date(2026, 11, 1))

assert page.log == ["#from=2026-11-01", "click #load"]
```

The decorated function is a **stub**: its body never runs, `fill_date`'s body does. The
stub gives the variant:

- its **name** (`fill_period_start`) and docstring (or the original's when it has none);
- its **parameters' markers and defaults**: here `value` became `Input()`. A parameter can
  also become `Depends(...)` or get a plain default.

Whether the step is a `step`, a `tap` or an [`output`](inputs.md#outputs) carries over from
the original. The stub exists because no type checker can express "the same parameters
with one default changed" from the original alone.

### What a variant must keep

The parameters after the subject must keep the **same names, order and kinds**
(positional, keyword-only...), or `InvalidStepError` is raised:

```python
from pyflowstep import InvalidStepError

try:

    @override(fill_date)
    def fill_x(page: Page, field: str, *, value: date) -> None: ...

except InvalidStepError as error:
    assert str(error).startswith("Override 'fill_x' must keep the parameters of 'fill_date'")
```

A parameter that is **processed** on the original must stay processed on the variant (or
be injected), otherwise JSON strings would reach the body unconverted:

```python
try:

    @override(fill_date)
    def fill_today(page: Page, selector: str, *, value: date = date(2026, 11, 26)) -> None: ...

except InvalidStepError as error:
    assert "drops the Process of 'value' from 'fill_date'" in str(error)


@override(fill_date)
def fill_cutoff(page: Page, selector: str, *, value: Annotated[date, Process(date.fromisoformat)] = date(2026, 11, 25)) -> None: ...


assert fill_cutoff("#cutoff")(Page()).log == ["#cutoff=2026-11-25"]
```

Only step factories can be overridden; a plain function raises `InvalidStepError`.

To register a variant for JSON flows, use `registry.override`:

```python
@portal.override(portal["fill_date"], name="fill_period_end")
def _fill_period_end(page: Page, selector: str, *, value: date = Input()) -> None: ...


assert "fill_period_end" in portal
```

## Chains

A **chain** names a group of steps. Its parameters are build arguments, like a step's,
but there is no subject: the function returns the `Flow` to run.

```python
@chain
def run_payroll(month: Annotated[str, Process(str.strip)]) -> Flow[Page]:
    """Load the month's attendance, compute and approve."""
    return click(f"#month-{month}") >> click("#compute") >> click("#approve")


november = run_payroll(" 2026-11 ") >> click("#export")

assert repr(november) == "Flow(click >> click >> click >> click)"
assert november(Page()).log == ["click #month-2026-11", "click #compute", "click #approve", "click #export"]
```

The flow stays **flat**: a chain adds its steps, not a nested flow, and the
[run inputs](inputs.md) of those steps become inputs of any flow the chain joins.

### Why `@chain` and not a function?

There are three ways to reuse a group of steps:

| | Takes arguments | Argument errors and `Process` like a step | Usable from JSON |
| --- | --- | --- | --- |
| a flow value: `approve = click("#compute") >> click("#approve")` | no | — | no |
| a plain function returning a flow | yes | no: plain `TypeError`s | no |
| `@chain`, or `@registry.chain()` | yes | yes | with the registry |

```python
from pyflowstep import MissingArgumentError

try:
    run_payroll()
except MissingArgumentError as error:
    assert str(error) == "missing a required argument: 'month' for step 'run_payroll'"
```

### Chains in JSON

Register the chain to use it in a [JSON flow](compiling.md):

```python
from pyflowstep import FlowCompiler


@portal.chain()
def close_month(month: str) -> Flow[Page]:
    """Run payroll for the month and lock it."""
    return run_payroll(month) >> click("#lock")


flow = FlowCompiler(portal.steps).compile([{"name": "close_month", "args": ["2026-10"]}])

assert flow(Page()).log[-1] == "click #lock"
```

### Rules of chains

- A chain cannot declare `Input()` or `Depends(...)`: it has no run of its own. Declare
  them on the steps it returns. Doing so raises `InvalidStepError` when it is defined.
- A chain must return a `Flow`; anything else raises `InvalidStepError` when it is called.

```python
try:

    @chain
    def forgot(month: str) -> Flow[Page]:
        click("#compute")  # no return

    forgot("2026-11")
except InvalidStepError as error:
    assert str(error) == "Chain 'forgot' must return a Flow, got None"
```
