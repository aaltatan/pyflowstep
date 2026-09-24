"""End-to-end user stories built on the two examples, plus sibling-library interop."""

import json
from dataclasses import dataclass, replace
from decimal import Decimal

import pytest
from pyformula import variable
from pyspecification import object_rule

from examples.browser import Page, click, fill, navigate, page_steps, wait
from examples.coffee import (
    Drink,
    Milk,
    add_milk,
    add_syrup,
    barista,
    brew,
    discount,
    menu,
    order,
    size,
    top_with,
)
from examples.coffee import compiler as coffee_compiler
from pyflowstep import (
    Flow,
    FlowCompiler,
    ProcessArgumentError,
    StepDoesNotExistError,
    compose,
    get_flow_json_schema,
    step,
    tap,
)

page_compiler = FlowCompiler(page_steps.steps)

LOGIN_SCENARIO = """
[
    {"name": "navigate", "args": ["https://example.com/login"]},
    {"name": "fill", "args": ["#email", "ada@example.com"]},
    {"name": "fill", "kwargs": {"selector": "#password", "value": "hunter2"}},
    {"name": "click", "args": ["button[type=submit]"]},
    {"name": "wait", "args": ["#dashboard"], "kwargs": {"timeout": "10"}}
]
"""


class TestBrowserAutomation:
    """As a QA engineer, I describe browser scenarios as flows instead of method chains."""

    def test_python_scenario(self) -> None:
        page = Page()
        search = navigate("https://www.google.com") >> fill("input[name=q]", 1111) >> click("#go")

        assert search(page) is page
        assert page.history == [
            "Navigating to https://www.google.com",
            "Filling input[name=q] with 1111",
            "Clicking on #go",
        ]

    def test_the_same_scenario_runs_on_many_pages(self) -> None:
        scenario = navigate("https://example.com") >> wait("body")
        pages = [Page(), Page()]

        for page in pages:
            scenario(page)

        assert pages[0].history == pages[1].history

    def test_stored_json_scenario(self) -> None:
        page = Page()
        page_compiler.compile(json.loads(LOGIN_SCENARIO))(page)

        assert page.history == [
            "Navigating to https://example.com/login",
            "Filling #email with ada@example.com",
            "Filling #password with hunter2",
            "Clicking on button[type=submit]",
            "Waiting for #dashboard (10.0s)",
        ]

    def test_insecure_url_is_rejected_before_the_browser_opens(self) -> None:
        scenario = json.dumps(
            [
                {"name": "fill", "args": ["#q", "x"]},
                {"name": "navigate", "args": ["http://insecure.example.com"]},
            ],
        )

        with pytest.raises(ProcessArgumentError, match="only https urls") as info:
            page_compiler.compile(json.loads(scenario))

        assert info.value.__notes__ == ["at $[1]"]

    def test_a_failing_step_says_where_it_failed(self) -> None:
        class BrokenPage(Page):
            def click(self, selector: str) -> None:
                msg = f"no element matches {selector}"
                raise LookupError(msg)

        page = BrokenPage()
        scenario = navigate("https://example.com") >> click("#missing") >> wait("#never")

        with pytest.raises(LookupError, match="#missing"):
            scenario(page)

        assert page.history == ["Navigating to https://example.com"]

    def test_scenarios_are_built_from_data(self) -> None:
        form = {"#first": "Ada", "#last": "Lovelace", "#year": 1815}
        fill_form = compose(*(fill(selector, value) for selector, value in form.items()))
        page = Page()

        (fill_form >> click("#save"))(page)

        assert len(page.history) == 4
        assert page.history[-1] == "Clicking on #save"

    def test_json_schema_lists_the_page_language(self) -> None:
        schema = get_flow_json_schema(page_steps.steps)
        names = [item["properties"]["name"]["const"] for item in schema["items"]["oneOf"]]
        assert names == ["navigate", "click", "fill", "wait"]


class TestCoffeeShop:
    """As a barista, I build drinks from a JSON menu and customize them per order."""

    def test_menu_items(self) -> None:
        mocha = order("mocha")

        assert mocha.base == "espresso"
        assert mocha.shots == 2
        assert mocha.milk is Milk.OAT
        assert mocha.syrups == (("chocolate", 2),)
        assert mocha.toppings == ("whipped cream", "cocoa")
        assert mocha.price == Decimal("4.70")

    def test_extras_are_applied_after_the_recipe(self) -> None:
        latte = order("latte", size("L"), add_syrup(" Vanilla "))

        assert latte.size == "L"
        assert latte.syrups == (("vanilla", 1),)
        assert latte.price == Decimal("3.65")

    def test_flows_are_pure(self) -> None:
        cup = Drink()
        first = menu["latte"](cup)
        second = menu["latte"](cup)

        assert cup == Drink()
        assert first == second
        assert first is not second

    def test_staff_only_discount_is_python_only(self) -> None:
        assert "discount" not in barista.steps
        assert order("espresso", discount(Decimal(50))).price == Decimal("1.65")

        with pytest.raises(StepDoesNotExistError, match="'discount'"):
            coffee_compiler.compile([{"name": "discount", "args": [100]}])

    def test_unknown_milk_is_rejected_when_the_menu_loads(self) -> None:
        recipe = [{"name": "brew", "args": ["drip"]}, {"name": "add_milk", "args": ["goat"]}]

        with pytest.raises(ProcessArgumentError, match="'goat' is not a valid Milk") as info:
            coffee_compiler.compile(recipe)  # type: ignore[arg-type]

        assert info.value.__notes__ == ["at $[1]"]

    def test_menu_can_be_written_by_hand_or_as_json(self) -> None:
        by_hand = brew("espresso") >> add_milk(Milk.WHOLE, ml=200)
        assert by_hand(Drink()) == menu["latte"](Drink())

    def test_toppings_accept_any_number_of_values(self) -> None:
        drink = (brew("drip") >> top_with() >> top_with("A", "b ", " C"))(Drink())
        assert drink.toppings == ("a", "b", "c")


@dataclass(frozen=True)
class Invoice:
    subtotal: Decimal
    tax: Decimal = Decimal(0)
    notes: tuple[str, ...] = ()


class TestSiblingLibraries:
    """As a pyspecification/pyformula user, I plug predicates and formulas into steps."""

    def test_predicate_as_a_guard_step(self) -> None:
        @object_rule()
        def is_large(invoice: Invoice, limit: Decimal) -> bool:
            return invoice.subtotal >= limit

        @step
        def note_if(invoice: Invoice, rule: object, note: str) -> Invoice:
            return replace(invoice, notes=(*invoice.notes, note)) if rule(invoice) else invoice  # type: ignore[operator]

        flow = note_if(is_large(Decimal(100)) & ~is_large(Decimal(1000)), "needs approval")

        assert flow(Invoice(Decimal(500))).notes == ("needs approval",)
        assert flow(Invoice(Decimal(50))).notes == ()
        assert flow(Invoice(Decimal(5000))).notes == ()

    def test_formula_as_a_computation_step(self) -> None:
        @variable()
        def subtotal(invoice: Invoice) -> Decimal:
            return invoice.subtotal

        @step
        def apply_tax(invoice: Invoice, formula: object) -> Invoice:
            return replace(invoice, tax=Decimal(str(formula(invoice))))  # type: ignore[operator]

        invoice = apply_tax(round(subtotal * 0.15, 2))(Invoice(Decimal(80)))
        assert invoice.tax == Decimal("12.0")


class TestFlowsAreValues:
    """As a developer, I pass flows around, store them and combine them like any value."""

    def test_conditional_composition(self) -> None:
        log: list[str] = []

        @tap
        def say(_: object, word: str) -> None:
            log.append(word)

        def greeting(*, polite: bool) -> Flow[object]:
            return say("hello") >> (say("please") if polite else Flow()) >> say("bye")

        greeting(polite=True)(None)
        greeting(polite=False)(None)
        assert log == ["hello", "please", "bye", "hello", "bye"]

    def test_flow_as_a_step_argument(self) -> None:
        @step
        def repeat(n: int, flow: Flow[int], times: int) -> int:
            return compose(*[flow] * times)(n)

        @step
        def inc(n: int) -> int:
            return n + 1

        assert repeat(inc() >> inc(), times=3)(0) == 6

    def test_compiler_with_a_custom_step_mapping(self) -> None:
        @step
        def inc(n: int) -> int:
            return n + 1

        aliases = {"inc": inc, "increment": inc, "plus_one": inc}
        flow = FlowCompiler[int](aliases).compile([{"name": name} for name in aliases])
        assert flow(0) == 3
