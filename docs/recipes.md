# Recipes

Complete, runnable programs for common jobs. Each one is self-contained.

## A daily sales import (ETL)

Every night a retailer imports the branches' sales exports: clean the rows, drop
duplicates and test lines, convert types, and total per branch. Each stage is a step over
an immutable tuple of rows, so every stage is easy to test on its own.

```python
import csv
import io
from collections import defaultdict
from datetime import date
from decimal import Decimal

from pyflowstep import step, tap

type Rows = tuple[dict[str, object], ...]

EXPORT = """\
branch,day,sku,qty,price
 Damascus ,2026-11-25,A-1,2,10.50
Damascus,2026-11-25,A-1,2,10.50
Aleppo,2026-11-25,B-7,1,99.00
Aleppo,2026-11-25,TEST,1,0
Homs,2026-11-25,A-1,3,10.50
"""


@step
def strip_text(rows: Rows) -> Rows:
    return tuple({k: v.strip() if isinstance(v, str) else v for k, v in row.items()} for row in rows)


@step
def drop_where(rows: Rows, field: str, *values: str) -> Rows:
    return tuple(row for row in rows if row[field] not in values)


@step
def deduplicate(rows: Rows) -> Rows:
    seen: set[tuple] = set()
    unique = []

    for row in rows:
        if (key := tuple(row.values())) not in seen:
            seen.add(key)
            unique.append(row)

    return tuple(unique)


@step
def convert(rows: Rows) -> Rows:
    return tuple(
        {**row, "day": date.fromisoformat(row["day"]), "qty": int(row["qty"]), "price": Decimal(row["price"])}
        for row in rows
    )


@step
def total_by(rows: Rows, field: str) -> Rows:
    totals: dict[object, Decimal] = defaultdict(Decimal)

    for row in rows:
        totals[row[field]] += row["qty"] * row["price"]

    return tuple({field: key, "total": value} for key, value in sorted(totals.items()))


report_log: list[str] = []


@tap
def log_count(rows: Rows, stage: str) -> None:
    report_log.append(f"{stage}: {len(rows)} rows")


nightly = (
    log_count("read")
    >> strip_text()
    >> drop_where("sku", "TEST")
    >> deduplicate()
    >> log_count("clean")
    >> convert()
    >> total_by("branch")
)

rows = tuple(csv.DictReader(io.StringIO(EXPORT)))

assert nightly(rows) == (
    {"branch": "Aleppo", "total": Decimal("99.00")},
    {"branch": "Damascus", "total": Decimal("21.00")},
    {"branch": "Homs", "total": Decimal("31.50")},
)
assert report_log == ["read: 5 rows", "clean: 3 rows"]
```

`strip_text` runs before `deduplicate`, so `" Damascus "` and `"Damascus"` are seen as the
same row. Reordering stages is a one-line change.

## Documents assembled from a template file

An HR department issues employment certificates. Each company in the group has its own
layout, kept in a TOML file; the steps know how to add each kind of block.

```python
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from pyflowstep import FlowCompiler, Input, StepsRegistry


@dataclass(frozen=True)
class Employee:
    name: str
    title: str
    hired: date


@dataclass
class Document:
    lines: list[str] = field(default_factory=list)


blocks = StepsRegistry[Document]()


@blocks.tap()
def heading(doc: Document, text: str) -> None:
    """A centred title."""
    doc.lines.append(text.upper().center(40))


@blocks.tap()
def paragraph(doc: Document, template: str, employee: Employee = Input()) -> None:
    """A paragraph; {name}, {title} and {hired} are replaced."""
    doc.lines.append(template.format(name=employee.name, title=employee.title, hired=f"{employee.hired:%d %B %Y}"))


@blocks.tap()
def blank(doc: Document, lines: int = 1) -> None:
    """Empty lines."""
    doc.lines.extend([""] * lines)


@blocks.tap()
def signature(doc: Document, signer: str, role: str) -> None:
    """A signature block."""
    doc.lines.extend([f"{signer}", f"{role}"])


TEMPLATE = """
[[steps]]
name = "heading"
args = ["Employment certificate"]

[[steps]]
name = "blank"

[[steps]]
name = "paragraph"
args = ["This certifies that {name} has worked with us as {title} since {hired}."]

[[steps]]
name = "blank"
kwargs = { lines = 2 }

[[steps]]
name = "signature"
args = ["Huda Sabbagh", "HR Manager"]
"""

folder = Path(tempfile.mkdtemp())
(folder / "certificate.toml").write_text(TEMPLATE, "utf-8")

certificate = FlowCompiler(blocks.steps).compile_file(folder / "certificate.toml")

doc = certificate(Document(), employee=Employee("Rana Haddad", "accountant", date(2021, 3, 1)))

assert doc.lines[2] == "This certifies that Rana Haddad has worked with us as accountant since 01 March 2021."
assert doc.lines[-2:] == ["Huda Sabbagh", "HR Manager"]
assert certificate.inputs == frozenset({"employee"})
```

A second company only needs a second TOML file. The employee is a
[run input](guide/inputs.md): the template is compiled once and reused for every
certificate.

## A purchase request with an approval step

A procurement system creates a purchase request, notifies the approver with the request
number, and records an audit entry. The database is a [dependency](guide/dependencies.md);
the number assigned on insert flows to later steps as an [output](guide/inputs.md#outputs).

```python
import sqlite3
from collections.abc import Iterator

from pyflowstep import Depends, output


@dataclass(frozen=True)
class Request:
    item: str
    amount: Decimal
    requester: str


def get_db() -> Iterator[sqlite3.Connection]:
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE request (id INTEGER PRIMARY KEY, item TEXT, amount TEXT, requester TEXT)")
    db.execute("CREATE TABLE audit (request_id INTEGER, event TEXT)")

    try:
        yield db
        db.commit()
    finally:
        db.close()


DB = Depends(get_db)
notifications: list[str] = []


@output("request_id")
def insert(request: Request, db: sqlite3.Connection = DB) -> int:
    cursor = db.execute(
        "INSERT INTO request (item, amount, requester) VALUES (?, ?, ?)",
        (request.item, str(request.amount), request.requester),
    )
    return cursor.lastrowid


@tap
def audit(request: Request, event: str, request_id: int = Input(), db: sqlite3.Connection = DB) -> None:
    db.execute("INSERT INTO audit VALUES (?, ?)", (request_id, event))


@tap
def notify(request: Request, approver: str, request_id: int = Input()) -> None:
    notifications.append(f"to {approver}: please approve PR-{request_id} ({request.item}, {request.amount})")


@output("audit_count")
def count_audit(request: Request, db: sqlite3.Connection = DB) -> int:
    return db.execute("SELECT count(*) FROM audit").fetchone()[0]


@tap
def check(request: Request, audit_count: int = Input()) -> None:
    assert audit_count == 2


submit = insert() >> audit("created") >> notify("finance@company.example") >> audit("notified") >> count_audit() >> check()

assert submit.inputs == frozenset()

submit(Request("Laptop", Decimal("950"), "omar"))

assert notifications == ["to finance@company.example: please approve PR-1 (Laptop, 950)"]
```

Every step of the run shares one connection; it is committed and closed when the run
ends, or only closed if a step fails.

## Testing a flow

Flows are values, so tests can build them, swap dependencies and check results without a
browser or a database.

```python
from pyflowstep import MissingInputError, override_dependencies


class FakeMailer:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, to: str, subject: str) -> None:
        self.sent.append((to, subject))


def get_mailer() -> FakeMailer:
    raise RuntimeError("no SMTP server in tests")


@dataclass(frozen=True)
class Signup:
    email: str
    verified: bool = False


@tap
def send_verification(signup: Signup, mailer: FakeMailer = Depends(get_mailer)) -> None:
    mailer.send(signup.email, "Verify your email")


@step
def mark_verified(signup: Signup, token: str = Input()) -> Signup:
    return Signup(signup.email, verified=token == "ok")


register = send_verification() >> mark_verified()


def test_register_sends_one_email_and_verifies() -> None:
    fake = FakeMailer()

    with override_dependencies({get_mailer: lambda: fake}):
        result = register(Signup("lina@example.com"), token="ok")

    assert result.verified
    assert fake.sent == [("lina@example.com", "Verify your email")]


def test_register_needs_a_token() -> None:
    try:
        register(Signup("lina@example.com"))
    except MissingInputError as error:
        assert "token" in str(error)
    else:
        raise AssertionError("expected MissingInputError")


test_register_sends_one_email_and_verifies()
test_register_needs_a_token()
```

The missing-input check runs before the first step, so the second test never reaches the
real `get_mailer`.
