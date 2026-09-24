"""Processors: turn raw strings from a web form into typed step arguments.

A shop lets users filter its catalog with a form. Everything a form sends is a
string ("4", "yes", "  HeadPhones "), while the steps want numbers, booleans and
clean text. Processors bridge that gap, and this example shows every form:

    (nothing)                              arguments are used as given
    processors=Decimal                     one processor for every argument
    processors={"limit": int}              only the named arguments
    processors={"min_stars": float, ...: normalize}
                                           the named ones, and `...` for all the others

Run it with `uv run python -m examples.processors`.
"""

from dataclasses import dataclass
from decimal import Decimal

from pyflowstep import FlowCompiler, InvalidProcessorsError, StepsRegistry


@dataclass(frozen=True, slots=True)
class Product:
    name: str
    brand: str
    category: str
    price: Decimal
    stars: float
    in_stock: bool


type Catalog = tuple[Product, ...]


def normalize(text: str) -> str:
    """Trim and lowercase, so "  HeadPhones " matches "headphones"."""
    return text.strip().lower()


def parse_bool(text: str) -> bool:
    """Read checkbox-like values: yes/no, true/false, on/off, 1/0."""
    return normalize(text) in {"yes", "true", "on", "1"}


catalog_steps = StepsRegistry[Catalog]()


# 1. No processors: the value reaches the step exactly as it was given.
@catalog_steps.step()
def in_category(products: Catalog, category: str) -> Catalog:
    """Keep products of one category."""
    return tuple(product for product in products if product.category == category)


# 2. A single callable: applied to every argument.
@catalog_steps.step(processors=Decimal)
def price_between(products: Catalog, low: Decimal, high: Decimal) -> Catalog:
    """Keep products whose price is within [low, high]."""
    return tuple(product for product in products if low <= product.price <= high)


# 3. A mapping: only the named arguments are processed, `by` stays a plain string.
@catalog_steps.step(processors={"limit": int})
def top(products: Catalog, by: str, limit: int = 3) -> Catalog:
    """Keep the `limit` best products by a numeric field."""
    return tuple(sorted(products, key=lambda product: getattr(product, by), reverse=True)[:limit])


# 4. A mapping with `...`: `min_stars` becomes a float, every other argument is normalized.
@catalog_steps.step(processors={"min_stars": float, ...: normalize})
def search(products: Catalog, text: str, min_stars: float = 0) -> Catalog:
    """Keep well-rated products whose name contains `text`."""
    return tuple(
        product
        for product in products
        if text in product.name.lower() and product.stars >= min_stars
    )


# 5. `...` also covers the extra keywords collected by `**fields`.
@catalog_steps.step(processors={"in_stock": parse_bool, ...: normalize})
def where(products: Catalog, *, in_stock: bool = False, **fields: str) -> Catalog:
    """Keep products matching every given text field, e.g. brand="sonic"."""
    return tuple(
        product
        for product in products
        if (product.in_stock or not in_stock)
        and all(getattr(product, key).lower() == value for key, value in fields.items())
    )


CATALOG: Catalog = (
    Product("Studio Headphones", "Sonic", "audio", Decimal("149.00"), 4.7, in_stock=True),
    Product("Travel Headphones", "Sonic", "audio", Decimal("89.00"), 4.2, in_stock=True),
    Product("Budget Headphones", "Sonic", "audio", Decimal("19.00"), 3.1, in_stock=True),
    Product("Pro Headphones", "Sonic", "audio", Decimal("349.00"), 4.9, in_stock=True),
    Product("Kids Headphones", "Sonic", "audio", Decimal("39.00"), 4.4, in_stock=False),
    Product("Bass Headphones", "Boom", "audio", Decimal("129.00"), 4.6, in_stock=True),
    Product("Desk Lamp", "Lumen", "home", Decimal("45.00"), 4.8, in_stock=True),
)


def main() -> None:
    compiler = FlowCompiler(catalog_steps.steps)
    filters = compiler.compile(
        [
            {"name": "in_category", "args": ["audio"]},
            {"name": "search", "args": ["  HeadPhones "], "kwargs": {"min_stars": "4"}},
            {"name": "where", "kwargs": {"in_stock": "yes", "brand": " SONIC "}},
            {"name": "price_between", "args": ["20", "200"]},
            {"name": "top", "kwargs": {"by": "stars", "limit": "2"}},
        ]
    )

    print(filters)
    for product in filters(CATALOG):
        print(f"{product.name} ({product.brand}) ${product.price} {product.stars}*")

    # A typo in a processor key is caught when the step is registered, not later.
    try:

        @catalog_steps.step(processors={"limt": int})
        def first(products: Catalog, limit: int) -> Catalog:
            return products[:limit]

    except InvalidProcessorsError as error:
        print(f"InvalidProcessorsError: {error}")


if __name__ == "__main__":
    main()
