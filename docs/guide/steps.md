# Steps and flows

## `@step`

A **step function** takes the subject first and returns the subject (the same object or
a new one):

```py
@step
def fill(page: Page, selector: str, value: str) -> Page: ...
```

`@step` turns it into a **step factory**: calling `fill("#email", "ada@x.sy")` returns a
one-step `Flow`, ready to compose.

### Example: cleaning customer records

A CRM imports customer records from several sources and normalises each one the same way.

```python
from inspect import signature

from pyflowstep import step

type Record = dict[str, str]


@step
def strip_all(record: Record) -> Record:
    """Trim spaces around every value."""
    return {key: value.strip() for key, value in record.items()}


@step
def lower(record: Record, *fields: str) -> Record:
    return {key: value.lower() if key in fields else value for key, value in record.items()}


@step
def rename(record: Record, old: str, new: str) -> Record:
    return {(new if key == old else key): value for key, value in record.items()}


@step
def default(record: Record, field: str, value: str) -> Record:
    return {**record, field: record.get(field) or value}


normalise = strip_all() >> rename("mail", "email") >> lower("email") >> default("country", "SY")

raw = {"name": " Rana Haddad ", "mail": " Rana@Example.COM ", "country": ""}

assert normalise(raw) == {"name": "Rana Haddad", "email": "rana@example.com", "country": "SY"}
assert raw["mail"] == " Rana@Example.COM "  # the steps returned new dicts
```

Any signature works: defaults, keyword-only parameters, `*args` (`*fields`) and
`**kwargs`. The factory has the signature of the function **without the subject**:

```python
assert str(signature(rename)) == "(old: str, new: str)"
assert rename.__name__ == "rename"
assert strip_all.__doc__ == "Trim spaces around every value."
```

### Arguments are checked when the flow is built

Calling a factory binds its arguments immediately. A mistake raises an
[`ArgumentError`](arguments.md#argument-errors) subclass then, not when the flow runs
over the 10,000th record:

```python
from pyflowstep import TooManyArgumentsError, UnexpectedKeywordArgumentError

try:
    rename("mail", "email", "extra")
except TooManyArgumentsError as error:
    assert str(error) == "too many positional arguments for step 'rename'"

try:
    default("country", "SY", overwrite=True)
except UnexpectedKeywordArgumentError as error:
    assert str(error) == "got an unexpected keyword argument 'overwrite' for step 'default'"
```

### What a step function must look like

The subject must be accepted **positionally** (first, not `*args`, not keyword-only).
Otherwise decorating raises `InvalidStepError`:

```python
from pyflowstep import InvalidStepError

try:

    @step
    def broken(*, record: Record) -> Record:
        return record

except InvalidStepError as error:
    assert "must accept the flow subject as its first positional parameter" in str(error)
```

A step factory cannot be decorated again; use it as it is:

```python
try:
    step(rename)
except InvalidStepError as error:
    assert "'rename' is already a step factory" in str(error)
```

## `@tap`

A **tap** is a step for side effects: its return value is ignored and the subject passes
through unchanged. No more `return page` at the end of every function that only *does*
something:

```python
audit_log: list[str] = []

from pyflowstep import tap


@tap
def log(record: Record, message: str) -> None:
    audit_log.append(f"{message}: {record.get('email', '?')}")


imported = (log("received") >> normalise >> log("normalised"))(raw)

assert imported["email"] == "rana@example.com"
assert audit_log == ["received: ?", "normalised: rana@example.com"]
```

Use taps for logging, sending messages, saving, and for subjects you mutate in place (a
browser page, a document being written).

## `Flow`

A `Flow[T]` is an immutable sequence of actions, each one `T -> T`. Calling it threads the
subject through every action, in order.

```py
Flow(*actions)
flow(subject, /, **inputs)
```

### Composing with `>>`

`>>` joins flows into a new flow. The operands never change, so a flow is a safe building
block:

```python
from pyflowstep import Flow

base = strip_all() >> lower("email")
with_country = base >> default("country", "SY")

assert len(base) == 2
assert len(with_country) == 3
assert repr(with_country) == "Flow(strip_all >> lower >> default)"
```

Composed flows are **flat**: joining flows of 2 and 3 steps gives a flow of 5 steps, not
a nested one, so `repr`, `len` and iteration show every step.

### Plain callables are welcome

Either side of `>>` may be any callable `T -> T`, such as a lambda or a function from
another library. A lambda shows as `<lambda>` in `repr`:

```python
shout = with_country >> (lambda record: {**record, "name": record["name"].upper()})

assert shout(raw)["name"] == "RANA HADDAD"
assert repr(shout) == "Flow(strip_all >> lower >> default >> <lambda>)"
assert (str.strip >> Flow[str](str.title))("  hello world ") == "Hello World"
```

### Members

| Member | Description |
| --- | --- |
| `flow(subject, /, **inputs)` | run every action; keyword arguments are [run inputs](inputs.md) |
| `a >> b` | a new flow: the actions of `a`, then those of `b` |
| `flow.actions` | the tuple of actions, in order |
| `len(flow)`, `iter(flow)` | number of actions, iteration over them |
| `flow.inputs` | the [run inputs](inputs.md) the caller must give |
| `flow.signature(stub)` | a [typed call](inputs.md#typed-calls) for type checkers |
| `bool(flow)` | always `True`, even for an empty flow |
| `repr(flow)` | `Flow(step_a >> step_b)` |

`Flow()` with no actions is the identity: it returns the subject unchanged.

## `compose`

`compose(a, b, c)` is `Flow() >> a >> b >> c`. It is handy when the steps come from a
list:

```python
from pyflowstep import compose

steps_for_partner = {
    "shop": [strip_all(), lower("email")],
    "bank": [strip_all(), rename("mail", "email"), lower("email"), default("country", "SY")],
}

partner_flow = compose(*steps_for_partner["bank"])

assert partner_flow(raw) == normalise(raw)
assert compose()(raw) is raw
```

## Mutable or immutable subjects

Both work. With an **immutable** subject (frozen dataclasses, tuples, the dicts above
rebuilt by each step), every step returns a new value and earlier states stay intact:
easy to test and to reason about. With a **mutable** subject (a browser page, a file, a
DOM), steps act on it and taps avoid the `return subject` noise. Pick what the subject
naturally is.
