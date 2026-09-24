"""Coffee shop: build immutable drinks with pure steps and a JSON menu.

Every step returns a *new* `Drink` (via `dataclasses.replace`), so flows are
pure functions: the same recipe applied to the same cup always gives the same
drink, and nothing is ever mutated.

Run it with `uv run python -m examples.coffee`.
"""

from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pyflowstep import Flow, FlowCompiler, StepsRegistry, compose

type Base = Literal["espresso", "drip", "cold_brew"]
type Size = Literal["S", "M", "L"]


class Milk(StrEnum):
    WHOLE = "whole"
    OAT = "oat"
    ALMOND = "almond"


@dataclass(frozen=True, slots=True)
class Drink:
    base: Base | None = None
    shots: int = 0
    milk: Milk | None = None
    milk_ml: int = 0
    syrups: tuple[tuple[str, int], ...] = ()
    toppings: tuple[str, ...] = ()
    size: Size = "M"
    price: Decimal = Decimal("0.00")

    def describe(self) -> str:
        parts = [f"{self.size} {self.base or 'empty cup'}"]
        if self.shots:
            parts.append(f"{self.shots} shot(s)")
        if self.milk:
            parts.append(f"{self.milk_ml}ml {self.milk} milk")
        parts.extend(f"{pumps}x {flavor} syrup" for flavor, pumps in self.syrups)
        parts.extend(self.toppings)
        return f"{', '.join(parts)} -> ${self.price}"


BASE_PRICES: dict[str, Decimal] = {
    "espresso": Decimal("2.50"),
    "drip": Decimal("2.00"),
    "cold_brew": Decimal("3.00"),
}
EXTRA_SHOT_PRICE = Decimal("0.80")
SYRUP_PUMP_PRICE = Decimal("0.40")
SIZE_SURCHARGES: dict[str, Decimal] = {
    "S": Decimal("-0.50"),
    "M": Decimal("0.00"),
    "L": Decimal("0.75"),
}
MILK_PRICES: dict[Milk, Decimal] = {
    Milk.WHOLE: Decimal("0.00"),
    Milk.OAT: Decimal("0.60"),
    Milk.ALMOND: Decimal("0.70"),
}


def normalize_text[V](value: V) -> V | str:
    """Processor: trim and lowercase strings, leave every other value alone."""
    return value.strip().lower() if isinstance(value, str) else value


barista = StepsRegistry[Drink]()


@barista.step(processors=normalize_text)
def brew(drink: Drink, base: Base, shots: int = 1) -> Drink:
    """Brew the base of the drink."""
    price = BASE_PRICES[base] + EXTRA_SHOT_PRICE * (shots - 1)
    return replace(drink, base=base, shots=shots, price=drink.price + price)


@barista.step(processors={"kind": Milk})
def add_milk(drink: Drink, kind: Milk, ml: int = 150) -> Drink:
    """Add steamed milk."""
    return replace(drink, milk=kind, milk_ml=ml, price=drink.price + MILK_PRICES[kind])


@barista.step(processors={"pumps": int, ...: normalize_text})
def add_syrup(drink: Drink, flavor: str, pumps: int = 1) -> Drink:
    """Add pumps of a flavored syrup."""
    return replace(
        drink,
        syrups=(*drink.syrups, (flavor, pumps)),
        price=drink.price + SYRUP_PUMP_PRICE * pumps,
    )


@barista.step(processors=normalize_text)
def top_with(drink: Drink, *toppings: str) -> Drink:
    """Finish the drink with free toppings."""
    return replace(drink, toppings=(*drink.toppings, *toppings))


@barista.step(processors={"cup": str.upper})
def size(drink: Drink, cup: Size) -> Drink:
    """Choose the cup size, adjusting the price."""
    return replace(drink, size=cup, price=drink.price + SIZE_SURCHARGES[cup])


@barista.step(hidden=True, processors={"percent": Decimal})
def discount(drink: Drink, percent: Decimal) -> Drink:
    """Staff-only: never exposed to the JSON menu."""
    factor = 1 - percent / 100
    return replace(drink, price=(drink.price * factor).quantize(Decimal("0.01")))


MENU_JSON: dict[str, list[dict[str, object]]] = {
    "espresso": [{"name": "brew", "args": ["espresso"], "kwargs": {"shots": 2}}],
    "latte": [
        {"name": "brew", "args": ["Espresso"]},
        {"name": "add_milk", "args": ["whole"], "kwargs": {"ml": 200}},
    ],
    "mocha": [
        {"name": "brew", "args": ["espresso"], "kwargs": {"shots": 2}},
        {"name": "add_milk", "args": ["oat"]},
        {"name": "add_syrup", "args": ["Chocolate"], "kwargs": {"pumps": 2}},
        {"name": "top_with", "args": ["whipped cream", " cocoa "]},
    ],
}

compiler = FlowCompiler(barista.steps)
menu: dict[str, Flow[Drink]] = {
    name: compiler.compile(recipe)  # type: ignore  # noqa: PGH003
    for name, recipe in MENU_JSON.items()
}


def order(item: str, *extras: Flow[Drink]) -> Drink:
    """Make a menu item in a fresh cup, applying the customer's extras on top."""
    return (menu[item] >> compose(*extras))(Drink())


def main() -> None:
    print(order("espresso").describe())
    print(order("latte", size("L"), add_syrup("vanilla")).describe())
    print(order("mocha", size("S"), discount(Decimal(20))).describe())

    happy_hour = discount(Decimal(50))
    print((menu["latte"] >> happy_hour)(Drink()).describe())


if __name__ == "__main__":
    main()
