# With pyspecification and pyformula

pyflowstep is the orchestrator of a small family of packages built the same way:

| Package | Wraps | Composes with | Answers |
| --- | --- | --- | --- |
| [pyspecification](https://aaltatan.github.io/pyspecification/) | `T -> bool` | `&` `\|` `~` | does a rule apply? |
| [pyformula](https://aaltatan.github.io/pyformula/) | `T -> number` | `+ - * / ...` | how much? |
| pyflowstep | `T -> T` | `>>` | what happens, in which order? |

Predicates and formulas are plain callables, so they are ordinary step arguments: a
step can **apply a rule** to decide whether it acts, and **compute a formula** to set a
value.

```bash
uv add pyflowstep pyspecification pyformula
```

## Example: processing supplier invoices

An accounts-payable team processes each supplier invoice: compute the tax, flag large
invoices for approval, and set the payment date.

```python
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal

from pyformula import Formula, variable
from pyspecification import Predicate, object_rule

from pyflowstep import step


@dataclass(frozen=True)
class Invoice:
    supplier: str
    subtotal: Decimal
    issued: date
    tax: Decimal = Decimal(0)
    due: date | None = None
    flags: tuple[str, ...] = ()


@object_rule()
def subtotal__ge(invoice: Invoice, amount: Decimal) -> bool:
    return invoice.subtotal >= amount


@object_rule()
def supplier__in(invoice: Invoice, suppliers: list[str]) -> bool:
    return invoice.supplier in suppliers


@variable()
def subtotal(invoice: Invoice) -> Decimal:
    return invoice.subtotal


@step
def set_tax(invoice: Invoice, formula: Formula[Invoice]) -> Invoice:
    return replace(invoice, tax=formula(invoice))


@step
def flag_if(invoice: Invoice, rule: Predicate[Invoice, bool], flag: str) -> Invoice:
    return replace(invoice, flags=(*invoice.flags, flag)) if rule(invoice) else invoice


@step
def pay_in(invoice: Invoice, days: int) -> Invoice:
    return replace(invoice, due=invoice.issued + timedelta(days=days))


process = (
    set_tax(round(subtotal * Decimal("0.15"), 2))
    >> flag_if(subtotal__ge(Decimal(5000)) & ~supplier__in(["Damascus Steel"]), "needs approval")
    >> pay_in(30)
)

big = process(Invoice("Al-Noor Stationery", Decimal("7200"), date(2026, 11, 1)))
trusted = process(Invoice("Damascus Steel", Decimal("9000"), date(2026, 11, 1)))

assert big.tax == Decimal("1080.00")
assert big.flags == ("needs approval",)
assert trusted.flags == ()
assert big.due == date(2026, 12, 1)
```

The rule and the formula are values built once, when the flow is built, exactly like
`"needs approval"` and `30`.

## The whole flow as JSON

The three packages have JSON compilers. With a [`Process`](arguments.md) marker that
**compiles** its argument, a JSON flow can carry a rule and a formula inside a step's
arguments, so the accounts-payable policy becomes one document:

```python
import json
from typing import Annotated

from pyargprocessors import Process
from pyformula import FormulaCompiler, VariablesRegistry, decimal_literal
from pyspecification import ObjectRulesRegistry, PredicateCompiler

from pyflowstep import FlowCompiler, StepsRegistry

rules = ObjectRulesRegistry[Invoice, bool](operator="logical")
rules.register_rule(lambda invoice, amount: invoice.subtotal >= Decimal(str(amount)), name="subtotal__ge")
rules.register_rule(lambda invoice, suppliers: invoice.supplier in suppliers, name="supplier__in")

numbers = VariablesRegistry[Invoice]()
numbers.register_variable(lambda invoice: invoice.subtotal, name="subtotal")

predicates = PredicateCompiler(
    rules.rules,
    lambda wrapper: Predicate(lambda _: wrapper["operator"] == "all", operator="logical"),
)
formulas = FormulaCompiler(numbers.variables, literal=decimal_literal)

type Rule = Annotated[Predicate[Invoice, bool], Process(predicates.compile)]
type Amount = Annotated[Formula[Invoice], Process(formulas.compile)]

payables = StepsRegistry[Invoice]()


@payables.step(name="set_tax")
def set_tax_from_json(invoice: Invoice, formula: Amount) -> Invoice:
    return replace(invoice, tax=formula(invoice))


@payables.step(name="flag_if")
def flag_if_from_json(invoice: Invoice, rule: Rule, flag: str) -> Invoice:
    return replace(invoice, flags=(*invoice.flags, flag)) if rule(invoice) else invoice


@payables.step(name="pay_in")
def pay_in_from_json(invoice: Invoice, days: int) -> Invoice:
    return replace(invoice, due=invoice.issued + timedelta(days=days))


POLICY = json.loads("""
[
  {"name": "set_tax", "args": [{"round": {"operator": "multiply", "expressions": ["subtotal", 0.15]}, "ndigits": 2}]},
  {"name": "flag_if", "kwargs": {
    "flag": "needs approval",
    "rule": {"operator": "all", "expressions": [
      {"name": "subtotal__ge", "args": [5000], "kwargs": {}, "inverse": false},
      {"name": "supplier__in", "args": [["Damascus Steel"]], "kwargs": {}, "inverse": true}
    ]}
  }},
  {"name": "pay_in", "args": [30]}
]
""")

policy = FlowCompiler(payables.steps).compile(POLICY)

assert policy(Invoice("Al-Noor Stationery", Decimal("7200"), date(2026, 11, 1))) == big
```

Because the compilers run **inside `Process`**, a bad rule or formula in the policy fails
while the flow is compiled, with the step's path:

```python
from pyargprocessors import ProcessArgumentError

broken = [{"name": "set_tax", "args": [{"operator": "multiply", "expressions": ["subtotl", 0.15]}]}]

try:
    FlowCompiler(payables.steps).compile(broken)
except ProcessArgumentError as error:
    assert "Formula not found: subtotl" in str(error)
    assert error.__notes__ == ["at $[0]"]
```

## Choosing a branch

A flow runs every step. To choose **which** steps run, decide in a step with a rule:

```python
from pyflowstep import Flow


@step
def when(invoice: Invoice, rule: Predicate[Invoice, bool], then: Flow[Invoice]) -> Invoice:
    return then(invoice) if rule(invoice) else invoice


express = when(supplier__in(["Damascus Steel"]), pay_in(7) >> flag_if(subtotal__ge(0), "express"))

assert express(Invoice("Damascus Steel", Decimal("10"), date(2026, 11, 1))).due == date(2026, 11, 8)
assert express(Invoice("Other", Decimal("10"), date(2026, 11, 1))).due is None
```

The inner flow joins the outer run, so its [dependencies](dependencies.md) and
[run inputs](inputs.md) are shared.
