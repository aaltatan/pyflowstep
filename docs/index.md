# pyflowstep

**Compose plain functions into readable, reusable flows.**

Write each operation as a small function, chain them with `>>`, and get a flow you can
run, extend, store as JSON or TOML, and describe with JSON Schema. It is a functional
replacement for fluent interfaces (`obj.a().b().c()`): the operations do not have to live
on one class, and the chain itself is a value.

```py
onboarding = create_account("starter") >> send_welcome_email() >> schedule_call(days=3)
```

## A first taste

An online shop prepares every order the same way: apply a discount code, add shipping,
reserve stock and send a confirmation.

```python
from dataclasses import dataclass, field, replace
from decimal import Decimal

from pyflowstep import step, tap


@dataclass(frozen=True)
class Order:
    id: str
    subtotal: Decimal
    country: str
    total: Decimal = Decimal(0)
    notes: tuple[str, ...] = ()


@step
def apply_discount(order: Order, percent: int) -> Order:
    return replace(order, total=order.subtotal * (100 - percent) / 100)


@step
def add_shipping(order: Order, domestic: Decimal, abroad: Decimal) -> Order:
    fee = domestic if order.country == "SY" else abroad
    return replace(order, total=order.total + fee)


@step
def note(order: Order, text: str) -> Order:
    return replace(order, notes=(*order.notes, text))


sent: list[str] = []


@tap
def confirm(order: Order) -> None:
    sent.append(f"Order {order.id}: {order.total}")


prepare = apply_discount(10) >> add_shipping(Decimal("3"), Decimal("12")) >> note("paid online") >> confirm()

order = prepare(Order("A-17", Decimal("80"), "SY"))

assert order.total == Decimal("75")
assert order.notes == ("paid online",)
assert sent == ["Order A-17: 75"]
```

Each decorated function became a **step factory**: call it with its arguments and you get
a one-step `Flow`. Flows join with `>>` into new flows; running one threads the order
through every step.

### Build on it without changing it

```python
gift = prepare >> note("gift wrap")

assert repr(prepare) == "Flow(apply_discount >> add_shipping >> note >> confirm)"
assert repr(gift) == "Flow(apply_discount >> add_shipping >> note >> confirm >> note)"
```

### Mistakes fail while the flow is built

```python
from pyflowstep import MissingArgumentError

try:
    add_shipping(Decimal("3"))  # forgot the price abroad
except MissingArgumentError as error:
    assert str(error) == "missing a required argument: 'abroad' for step 'add_shipping'"
```

### Let operations staff define flows as JSON

```python
from pyflowstep import FlowCompiler, StepsRegistry

shop = StepsRegistry[Order]()


@shop.step()
def discount(order: Order, percent: int) -> Order:
    return replace(order, total=order.subtotal * (100 - percent) / 100)


@shop.step(name="note")
def add_note(order: Order, text: str) -> Order:
    return replace(order, notes=(*order.notes, text))


flow = FlowCompiler(shop.steps).compile(
    [
        {"name": "discount", "args": [25]},
        {"name": "note", "kwargs": {"text": "staff discount"}},
    ]
)

assert flow(Order("B-2", Decimal("40"), "LB")).total == Decimal("30")
```

## What else it does

- **[Argument processing](guide/arguments.md)**: turn the strings and numbers of JSON
  into dates, decimals and enums when the flow is built.
- **[Dependencies](guide/dependencies.md)**: give steps a database session or a mailer
  with `Depends`, one per run, cleaned up afterwards.
- **[Run inputs and outputs](guide/inputs.md)**: hand a flow per-run values
  (`flow(page, user=user)`), and pass values from one step to a later one.
- **[Variants and chains](guide/variants-and-chains.md)**: derive a step with other
  defaults, or name a group of steps.
- **[JSON and TOML](guide/compiling.md)** flows, with errors that point at the bad step,
  and a **[JSON Schema](guide/json-schema.md)** of your flow language.

## Where it fits

- **Browser and UI automation**: `navigate >> fill >> click`, scenarios as data.
- **Order, document and HR workflows**: the same steps, different flows per customer.
- **Data cleaning and ETL**: `strip >> parse_dates >> drop_duplicates >> save`.
- **Onboarding and provisioning**: a sequence of actions defined in a config file.

## Where to next

<div class="grid cards" markdown>

- [**Installation**](install.md): one command.
- [**User guide**](guide/index.md): every feature, one page each.
- [**Recipes**](recipes.md): complete real-world programs.
- [**API reference**](reference/api.md): every public name.

</div>
