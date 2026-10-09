"""Dependencies: give steps the objects that JSON cannot describe.

A shop stores its order-fulfilment flow as JSON. Some steps need a mailer and a
database session, and neither can be written in JSON. Each step declares what it
needs with `Depends(provider)`, and the provider is called when the flow runs:

    mailer: Mailer = Depends(get_mailer)     the marker is the default value
    session: Session = SESSION               the same marker, named once and reused

One flow run is one scope, like one request in a web framework:

- `get_session` runs once per flow run, so `save` and `audit` share one session
- it is a generator, so the session is committed or rolled back when the run ends
- `get_mailer` depends on `get_settings`, a sub-dependency

Run it with `uv run python -m examples.dependencies`.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Annotated

from pyflowstep import (
    Depends,
    FlowCompiler,
    Parse,
    StepsRegistry,
    UnexpectedKeywordArgumentError,
    get_step_json_schema,
    override_dependencies,
)


@dataclass(frozen=True, slots=True)
class Order:
    id: str
    customer: str
    total: Decimal
    status: str = "new"


# --- external objects: none of these can appear in JSON ---------------------


@dataclass(frozen=True, slots=True)
class Settings:
    smtp_host: str = "smtp.example.com"
    sender: str = "shop@example.com"


@dataclass(frozen=True, slots=True)
class Mailer:
    host: str
    sender: str

    def send(self, to: str, subject: str) -> None:
        print(f"  mail via {self.host}: {self.sender} -> {to}: {subject}")


class FakeMailer:
    def send(self, to: str, subject: str) -> None:
        print(f"  (fake mailer) would send '{subject}' to {to}")


@dataclass(slots=True)
class Session:
    rows: list[str] = field(default_factory=list)

    def add(self, row: str) -> None:
        self.rows.append(row)


# --- providers: plain functions that build those objects --------------------


def get_settings() -> Settings:
    return Settings()


def get_mailer(settings: Settings = Depends(get_settings)) -> Mailer:
    """Build the mailer; a provider can have dependencies of its own."""
    return Mailer(settings.smtp_host, settings.sender)


def get_session() -> Iterator[Session]:
    """Open one session per flow run, then commit or roll back when the run ends."""
    session = Session()
    print("  session opened")
    try:
        yield session
    except Exception:
        print("  session rolled back")
        raise
    else:
        print(f"  session committed: {', '.join(session.rows)}")
    finally:
        print("  session closed")


SESSION = Depends(get_session)


# --- steps -------------------------------------------------------------------

fulfilment_steps = StepsRegistry[Order]()


@fulfilment_steps.step()
def discount(order: Order, percent: Annotated[Decimal, Parse(Decimal)]) -> Order:
    """Apply a discount: an ordinary step, `percent` comes from the JSON."""
    return replace(order, total=order.total * (1 - percent / 100))


@fulfilment_steps.tap()
def save(order: Order, session: Session = SESSION) -> None:
    """Store the order. The session is injected, the JSON knows nothing about it."""
    session.add(f"order {order.id}")


@fulfilment_steps.step()
def charge(order: Order) -> Order:
    """Take the payment."""
    if order.total <= 0:
        msg = f"nothing to charge for order {order.id}"
        raise ValueError(msg)
    return replace(order, status="paid")


@fulfilment_steps.tap()
def send_email(order: Order, template: str, mailer: Mailer = Depends(get_mailer)) -> None:
    """Email the customer: `template` comes from the JSON, `mailer` is injected."""
    mailer.send(order.customer, f"{template} for order {order.id} (${order.total:.2f})")


@fulfilment_steps.tap()
def audit(order: Order, action: str, session: Session = SESSION) -> None:
    """Record what happened, in the same session `save` used."""
    session.add(f"audit {order.id} {action}")


# What would be stored as JSON. No mailer, no session.
FULFILMENT = [
    {"name": "discount", "args": ["10"]},
    {"name": "save"},
    {"name": "charge"},
    {"name": "send_email", "args": ["receipt"]},
    {"name": "audit", "kwargs": {"action": "fulfilled"}},
]


def main() -> None:
    compiler = FlowCompiler(fulfilment_steps.steps)
    fulfil = compiler.compile(FULFILMENT)  # type: ignore[arg-type]
    print(fulfil)

    print("\n--- a normal run: one session, shared by `save` and `audit` ---")
    order = fulfil(Order("o-1", "ada@example.com", Decimal("50.00")))
    print(f"  -> {order.status}")

    print("\n--- a failing run: the same flow, a fresh session, rolled back ---")
    try:
        fulfil(Order("o-2", "bob@example.com", Decimal("0.00")))
    except ValueError as error:
        print(f"  -> ValueError: {error}")

    print("\n--- in a test: swap the mailer for a fake ---")
    with override_dependencies({get_mailer: FakeMailer}):
        fulfil(Order("o-3", "eve@example.com", Decimal("20.00")))

    print("\n--- JSON can neither see nor set a dependency ---")
    schema = get_step_json_schema("send_email", fulfilment_steps["send_email"])
    print(f"  schema arguments: {list(schema['properties']['kwargs']['properties'])}")
    try:
        compiler.compile([{"name": "send_email", "kwargs": {"template": "x", "mailer": "evil"}}])
    except UnexpectedKeywordArgumentError as error:
        print(f"  {type(error).__name__}: {error} ({error.__notes__[0]})")


if __name__ == "__main__":
    main()
