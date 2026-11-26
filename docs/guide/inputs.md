# Run inputs and outputs

A flow is usually built once and run many times, each time for different data: another
user, another invoice, another date. Values that change **per run** are not step
arguments; they are **run inputs**, given when the flow is called:

```py
flow(subject, user=ada, voucher=voucher)
```

## `Input()`

A parameter whose default is `Input()` is not an argument of the step. The caller supplies
it by name when running the flow, and every step that declares it receives it:

```py
@step
def fill_amount(page: Page, selector: str, voucher: Voucher = Input()) -> Page: ...

entry = fill_amount("#amount")      # only `selector` is an argument
entry(page, voucher=voucher)        # `voucher` is supplied for this run
```

### Example: entering payment vouchers in an ERP

An accountant's assistant script enters each payment voucher into a web ERP. The flow is
the same for every voucher; the voucher is the run input.

```python
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from pyflowstep import Input, step, tap


@dataclass(frozen=True)
class Voucher:
    payee: str
    amount: Decimal
    day: date


class Page:
    def __init__(self) -> None:
        self.fields: dict[str, str] = {}
        self.saved: list[dict[str, str]] = []

    def save(self) -> str:
        self.saved.append(dict(self.fields))
        return f"PV-{len(self.saved):04d}"


@tap
def fill_payee(page: Page, selector: str, voucher: Voucher = Input()) -> None:
    page.fields[selector] = voucher.payee


@tap
def fill_amount(page: Page, selector: str, voucher: Voucher = Input()) -> None:
    page.fields[selector] = f"{voucher.amount:.2f}"


@tap
def fill_date(page: Page, selector: str, voucher: Voucher = Input(), date_format: str = Input(default="%Y-%m-%d")) -> None:
    page.fields[selector] = voucher.day.strftime(date_format)


enter_voucher = fill_payee("#payee") >> fill_amount("#amount") >> fill_date("#date")

page = Page()

enter_voucher(page, voucher=Voucher("Al-Noor Stationery", Decimal("125.5"), date(2026, 11, 3)))

assert page.fields == {"#payee": "Al-Noor Stationery", "#amount": "125.50", "#date": "2026-11-03"}

enter_voucher(page, voucher=Voucher("City Water", Decimal("40"), date(2026, 11, 4)), date_format="%d/%m/%Y")

assert page.fields["#date"] == "04/11/2026"
```

`Input(default=...)` makes an input optional: `date_format` falls back to ISO dates.

### Checked before anything runs

`flow.inputs` lists the inputs the caller **must** give (optional ones are not listed).
Calling a flow without one raises `MissingInputError` before the first step runs, naming
every missing input and the steps that need it, so a forgotten value never leaves the ERP
half filled:

```python
from pyflowstep import MissingInputError

assert enter_voucher.inputs == frozenset({"voucher"})

page = Page()

try:
    enter_voucher(page)
except MissingInputError as error:
    assert str(error) == (
        "missing run input 'voucher' for steps 'fill_payee', 'fill_amount', 'fill_date'; "
        "run the flow as flow(subject, voucher=...)"
    )

assert page.fields == {}  # nothing was typed
```

!!! warning "Unknown inputs are ignored"
    `enter_voucher(page, voucher=v, date_fromat="%d/%m/%Y")` runs with the default date
    format: an input no step declares is not an error, because a flow started inside a
    step may read it. To catch typos, give the flow a [typed signature](#typed-calls).

## Typed calls

`flow(page, voucher=...)` takes `**inputs`, so type checkers cannot check it.
`flow.signature` gives the flow a real signature, from a stub whose subject is
positional-only and whose inputs are keyword-only:

```python
@enter_voucher.signature
def enter(page: Page, /, *, voucher: Voucher, date_format: str = ...) -> Page: ...


page = Page()
enter(page, voucher=Voucher("City Water", Decimal("40"), date(2026, 11, 4)))

assert page.fields["#payee"] == "City Water"
```

The stub's body never runs. It must declare exactly the flow's inputs, required ones
without a default and optional ones with one (`...` is fine); otherwise
`InvalidInputError` is raised when it is decorated:

```python
from pyflowstep import InvalidInputError

try:

    @enter_voucher.signature
    def wrong(page: Page, /, *, voucher: Voucher, user: str) -> Page: ...

except InvalidInputError as error:
    assert str(error) == "Signature 'wrong' does not match the flow: missing input 'date_format'; unknown input 'user'"
```

Annotations are not compared, only names and whether each input is required.

## Outputs

Sometimes a later step needs a value an earlier step **produces**: the voucher number the
ERP assigns on save, the ID of a created record. `@output("name")` makes a step's return
value the run input `name` for the steps after it. The subject passes through unchanged,
like a [tap](steps.md#tap):

```python
from pyflowstep import output


@output("number")
def save(page: Page) -> str:
    return page.save()


@tap
def fill_reference(page: Page, selector: str, number: str = Input()) -> None:
    page.fields[selector] = f"See {number}"


enter_and_link = enter_voucher >> save() >> fill_reference("#memo") >> save()

assert enter_and_link.inputs == frozenset({"voucher"})  # `number` is produced inside

page = Page()
enter_and_link(page, voucher=Voucher("Al-Noor Stationery", Decimal("125.5"), date(2026, 11, 3)))

assert page.saved[1]["#memo"] == "See PV-0001"
```

`fill_reference` is an ordinary step with an ordinary `Input()`: it does not know whether
the number comes from the caller or from an earlier step, so it stays reusable.

### Order matters, and is checked

A step that reads an input **before** it is produced still needs it from the caller:

```python
too_early = fill_reference("#memo") >> save()

assert too_early.inputs == frozenset({"number"})
```

### Rules of outputs

- A later output of the same name replaces the earlier one for the steps after it.
- A produced value replaces one the caller passed, for the steps after the producer.
- A flow called **inside** a step with inputs of its own keeps its outputs to itself;
  called without inputs, it shares the run of the outer flow.
- The name must be a valid parameter name (an identifier, not a keyword), or
  `InvalidInputError` is raised.

## Rules of inputs

`InvalidInputError` is raised when the step is defined if `Input()`:

- is written inside `Annotated[...]` instead of as the default value,
- marks the subject,
- marks a positional-only parameter (inputs are passed by name).

[Dependency providers](dependencies.md) cannot take run inputs: only steps do. An
`Input()` parameter is not an argument, so it is not in the
[JSON Schema](json-schema.md) and a JSON flow cannot set it.

## `Input`, `Depends` or an output?

| The value... | Use |
| --- | --- |
| only the caller has (the voucher, the logged-in user) | `Input()` |
| a provider can build (a session, an API client) | [`Depends(provider)`](dependencies.md) |
| an earlier step of the same run computes | `@output("name")` + `Input()` |
| is part of the flow definition (`"#amount"`) | a normal argument |
