# Arguments and processing

Flows defined in JSON or TOML get their arguments as strings, numbers, booleans, lists and
objects. Step functions want dates, decimals, enums, compiled patterns. The `Process`
marker from [pyargprocessors](https://github.com/aaltatan/pyargprocessors) bridges the two.

## `Process`

Write `Annotated[Type, Process(fn)]` on a parameter, and `fn` runs on the value **when
the step is built**:

```python
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Annotated

from pyargprocessors import Process

from pyflowstep import step


@dataclass(frozen=True)
class Invoice:
    number: str
    issued: date
    total: Decimal
    due: date | None = None
    lines: tuple[str, ...] = ()


@step
def due_on(invoice: Invoice, day: Annotated[date, Process(date.fromisoformat)]) -> Invoice:
    return replace(invoice, due=day)


invoice = Invoice("INV-1", date(2026, 11, 1), Decimal("120"))

assert due_on("2026-12-01")(invoice).due == date(2026, 12, 1)  # a string, as JSON sends it
```

### Example: an invoice template defined in a config file

Finance keeps invoice adjustments in a TOML file; every value arrives as text or a plain
number. Name each processed type once with a `type` alias:

```python
from enum import StrEnum

from pyargprocessors import each


class Currency(StrEnum):
    SYP = "SYP"
    USD = "USD"


type Money = Annotated[Decimal, Process(lambda value: Decimal(str(value)))]
type Text = Annotated[str, Process(str.strip)]
type Codes = Annotated[list[str], Process(each(str.strip)), Process(each(str.upper))]


@step
def add_fee(invoice: Invoice, label: Text, amount: Money) -> Invoice:
    return replace(invoice, total=invoice.total + amount, lines=(*invoice.lines, f"{label}: {amount}"))


@step
def convert(invoice: Invoice, to: Annotated[Currency, Process(Currency)], rate: Money) -> Invoice:
    return replace(invoice, total=invoice.total * rate, lines=(*invoice.lines, f"in {to.value}"))


@step
def tag(invoice: Invoice, *codes: Annotated[str, Process(str.upper)]) -> Invoice:
    return replace(invoice, lines=(*invoice.lines, *codes))


adjust = add_fee(" Handling ", 2.5) >> add_fee("Insurance", "1.10") >> convert("USD", 0.5) >> tag("vip", "q4")

result = adjust(invoice)

assert result.total == Decimal("61.800")
assert result.lines == ("Handling: 2.5", "Insurance: 1.10", "in USD", "VIP", "Q4")
```

Markers on one parameter run **left to right**. `each(fn)` applies `fn` to every item of
a list (or every value of a dict), and `optional(fn)` (also from pyargprocessors) leaves
`None` alone.

## The rules of processing

- Processing happens **once, when the step is built**. The processed value is reused for
  every run of the flow.
- It applies whether the value was passed positionally or by keyword. On `*args` it runs
  on each item, on `**kwargs` on each value.
- **Defaults you did not pass are not processed**, so a default must already have the
  final type.
- Only arguments are processed: not the subject, and not parameters filled by
  [`Depends`](dependencies.md) or [`Input`](inputs.md).

### Processors can load data

A processor may accept something else than the step receives. Here the flow file names a
CSV of price overrides and the step receives the loaded table:

```python
import csv
import tempfile
from pathlib import Path


def load_prices(path: str) -> dict[str, Decimal]:
    with Path(path).open(encoding="utf-8", newline="") as file:
        return {row["sku"]: Decimal(row["price"]) for row in csv.DictReader(file)}


@step
def reprice(invoice: Invoice, prices: Annotated[dict[str, Decimal], Process(load_prices)]) -> Invoice:
    return replace(invoice, total=sum(prices.values(), Decimal(0)))


with tempfile.TemporaryDirectory() as folder:
    table = Path(folder) / "prices.csv"
    table.write_text("sku,price\nA-1,10.50\nB-2,4.25\n", "utf-8")

    reprice_step = reprice(str(table))  # the file is read here, once

assert reprice_step(invoice).total == Decimal("14.75")
```

The [JSON Schema](json-schema.md) of `prices` says `string`: it describes what the JSON
must send (the processor's parameter), not what the step receives.

## When a processor fails

A processor that raises becomes a `ProcessArgumentError` naming the argument and the
value, with the original exception chained:

```python
from pyargprocessors import ProcessArgumentError

try:
    due_on("01/12/2026")
except ProcessArgumentError as error:
    assert (error.argument, error.value) == ("day", "01/12/2026")
    assert isinstance(error.cause, ValueError)
    assert str(error).startswith("Argument 'day' with value '01/12/2026' failed to process")
```

Compiled from JSON, the error also carries the [path of the step](compiling.md#errors-point-at-the-step).

## Misplaced markers

`InvalidProcessorError` (a `TypeError`, from pyargprocessors) is raised when the step is
**defined** if a `Process` marker is not callable, sits on the subject, is written as a
default value instead of inside `Annotated`, or is combined with `Depends`/`Input` on the
same parameter (nothing is passed for those, so there is nothing to process):

```python
from pyargprocessors import InvalidProcessorError

from pyflowstep import Input

try:

    @step
    def stamp(invoice: Invoice, day: Annotated[date, Process(date.fromisoformat)] = Input()) -> Invoice:
        return invoice

except InvalidProcessorError as error:
    assert "cannot both process and inject ['day']" in str(error)
```

## Argument errors

Arguments are bound to the step's signature as soon as the factory is called, including
by the compiler. Each kind of mistake has its own exception, all subclasses of
`ArgumentError` (itself a `PyflowstepError` and a `TypeError`):

| Mistake | Exception | Example |
| --- | --- | --- |
| a required argument is missing | `MissingArgumentError` | `due_on()` |
| too many positional arguments | `TooManyArgumentsError` | `due_on("2026-12-01", "x")` |
| a keyword the step does not declare | `UnexpectedKeywordArgumentError` | `tag(color="red")` |
| a value given both positionally and by keyword | `MultipleValuesArgumentError` | `add_fee("Fee", 1, label="Fee")` |
| a positional-only parameter passed by keyword | `PositionalOnlyArgumentError` | `discount(percent=5)` for `def discount(i, percent, /)` |

```python
from pyflowstep import (
    ArgumentError,
    MissingArgumentError,
    MultipleValuesArgumentError,
    PositionalOnlyArgumentError,
    TooManyArgumentsError,
    UnexpectedKeywordArgumentError,
)


@step
def discount(invoice: Invoice, percent: int, /) -> Invoice:
    return replace(invoice, total=invoice.total * (100 - percent) / 100)


mistakes = [
    (lambda: due_on(), MissingArgumentError),
    (lambda: due_on("2026-12-01", "x"), TooManyArgumentsError),
    (lambda: tag(color="red"), UnexpectedKeywordArgumentError),
    (lambda: add_fee("Fee", 1, label="Fee"), MultipleValuesArgumentError),
    (lambda: discount(percent=5), PositionalOnlyArgumentError),
]

for build, expected in mistakes:
    try:
        build()
    except ArgumentError as error:
        assert type(error) is expected, (error, expected)
        assert "for step '" in str(error)
```

When several things are wrong, they are reported in the order Python reports them for a
normal call: keywords that cannot be passed by name first, then surplus or unknown
arguments, then missing ones. So `due_on(dya="2026-12-01")` is an unexpected `dya`, not
a missing `day`: the typo is what needs fixing.

```python
try:
    due_on(dya="2026-12-01")
except UnexpectedKeywordArgumentError as error:
    assert str(error) == "got an unexpected keyword argument 'dya' for step 'due_on'"
```

The messages are Python's own, followed by the step name, for example
`missing a required argument: 'day' for step 'due_on'`. A `TypeError` raised from
**inside** a step function while it runs is never turned into an `ArgumentError`.
