# Dependencies

Some things a step needs cannot be written in a flow definition: a database connection,
an HTTP client, a mailer, the current settings. Mark such a parameter with
`Depends(provider)`: nobody passes it, neither Python nor JSON, and `provider` is called
to produce it when the flow runs.

```py
def get_mailer() -> Mailer: ...

@step
def send_receipt(order: Order, template: str, mailer: Mailer = Depends(get_mailer)) -> Order: ...

send_receipt("receipt")  # only `template` is an argument
```

The design follows FastAPI's `Depends`: **one flow run is one scope**, like one request.

## Example: fulfilling an order

A warehouse service saves each shipped order in its database and emails the customer.

```python
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass, replace

from pyflowstep import Depends, step, tap

events: list[str] = []


def get_database() -> Iterator[sqlite3.Connection]:
    """One connection per run, committed and closed at the end."""
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE shipment (order_id TEXT, carrier TEXT)")
    events.append("open")

    try:
        yield connection
        connection.commit()
        events.append("commit")
    finally:
        connection.close()
        events.append("close")


class Mailer:
    def __init__(self) -> None:
        self.outbox: list[str] = []

    def send(self, to: str, text: str) -> None:
        self.outbox.append(f"{to}: {text}")


MAILER = Mailer()


def get_mailer() -> Mailer:
    return MAILER


DATABASE = Depends(get_database)  # name a dependency once, reuse it


@dataclass(frozen=True)
class Order:
    id: str
    email: str
    carrier: str = ""


@step
def ship_with(order: Order, carrier: str, db: sqlite3.Connection = DATABASE) -> Order:
    db.execute("INSERT INTO shipment VALUES (?, ?)", (order.id, carrier))
    return replace(order, carrier=carrier)


@tap
def check_saved(order: Order, db: sqlite3.Connection = DATABASE) -> None:
    (count,) = db.execute("SELECT count(*) FROM shipment WHERE order_id = ?", (order.id,)).fetchone()
    events.append(f"saved={count}")


@tap
def email_customer(order: Order, template: str, mailer: Mailer = Depends(get_mailer)) -> None:
    mailer.send(order.email, template.format(carrier=order.carrier))


fulfil = ship_with("DHL") >> check_saved() >> email_customer("Your order ships with {carrier}.")

shipped = fulfil(Order("A-17", "rana@example.com"))

assert shipped.carrier == "DHL"
assert events == ["open", "saved=1", "commit", "close"]
assert MAILER.outbox == ["rana@example.com: Your order ships with DHL."]
```

`ship_with` and `check_saved` received **the same connection**: within one run a provider
is called at most once and its object is shared. The next run gets a new one:

```python
events.clear()
fulfil(Order("A-18", "omar@example.com"))

assert events == ["open", "saved=1", "commit", "close"]
```

## Providers

A provider is any callable that takes no required arguments:

- a **function** returning the object;
- a **generator function** that `yield`s the object once and cleans up after the
  `yield`, when the run ends (like a `contextlib.contextmanager`).

Generator providers are cleaned up in reverse order of creation, after the last step.

### When a step fails

If a step raises, the error is thrown into every open generator provider at its `yield`,
so `try/finally` and `except` blocks run, and then the error is **re-raised**: a provider
cannot swallow it. Above, a failure means no commit, but the connection is still closed:

```python
@step
def out_of_stock(order: Order) -> Order:
    raise RuntimeError(f"{order.id} is out of stock")


events.clear()

try:
    (ship_with("DHL") >> out_of_stock())(Order("A-19", "lina@example.com"))
except RuntimeError as error:
    assert str(error) == "A-19 is out of stock"

assert events == ["open", "close"]
```

### Providers with dependencies

A provider's own parameters may use `Depends` too. Here a repository needs the database:

```python
class ShipmentRepository:
    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    def count(self) -> int:
        return self.db.execute("SELECT count(*) FROM shipment").fetchone()[0]


def get_repository(db: sqlite3.Connection = DATABASE) -> ShipmentRepository:
    return ShipmentRepository(db)


@tap
def report(order: Order, repo: ShipmentRepository = Depends(get_repository)) -> None:
    events.append(f"shipments={repo.count()}")


events.clear()
(ship_with("UPS") >> report())(Order("A-20", "sami@example.com"))

assert events == ["open", "shipments=1", "commit", "close"]
```

The repository and `ship_with` share the run's single connection.

## Replacing a dependency in tests

`override_dependencies({original: replacement})` swaps providers inside a `with` block,
so tests can use fakes without touching the steps. Blocks nest, and everything is
restored on exit:

```python
from pyflowstep import override_dependencies

fake = Mailer()

with override_dependencies({get_mailer: lambda: fake}):
    email_customer("Hello")(Order("T-1", "test@example.com"))

assert fake.outbox == ["test@example.com: Hello"]
assert "test@example.com: Hello" not in MAILER.outbox
```

## Rules

A `Depends` parameter is **not an argument**. Passing a value for it is an error, it does
not appear in the [JSON Schema](json-schema.md), and a [JSON flow](compiling.md) cannot
set it:

```python
from pyflowstep import TooManyArgumentsError

try:
    email_customer("Hello", MAILER)
except TooManyArgumentsError:
    pass
```

Mistakes in a declaration raise `InvalidDependencyError` (also a `TypeError`) when the step
is defined:

| Mistake | Why |
| --- | --- |
| `Depends(...)` inside `Annotated[...]` | only a default value tells type checkers the parameter is not passed |
| on the subject, or on a positional-only parameter | a dependency is passed by name |
| a provider with a required parameter that is not a dependency | nobody could pass it |
| a provider that takes an `Input()` | only steps receive [run inputs](inputs.md) |
| circular providers | they could never be built |
| `Depends(x)` where `x` is not callable | |

```python
from typing import Annotated

from pyflowstep import InvalidDependencyError


try:

    @step
    def wrong(order: Order, mailer: Annotated[Mailer, Depends(get_mailer)]) -> Order:
        return order

except InvalidDependencyError as error:
    assert "uses Depends inside Annotated for 'mailer'" in str(error)

try:

    @step
    def needs_arg(order: Order, client: object = Depends(lambda timeout: None)) -> Order:
        return order

except InvalidDependencyError as error:
    assert "has a required parameter 'timeout' that is not a dependency" in str(error)
```

## `Depends`, `Input` or an argument?

| The value... | Use |
| --- | --- |
| is part of what the flow does (`"#submit"`, `"DHL"`) | a normal argument |
| can be built by code without the caller (a session, a client, settings) | `Depends(provider)` |
| only the caller of the flow has (the logged-in user, the uploaded file) | [`Input()`](inputs.md) |
| is computed by an earlier step of the same run | an [output](inputs.md#outputs) |
