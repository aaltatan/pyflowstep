"""Parsing: turn raw strings from a web form into typed step arguments.

A shop lets users filter its catalog with a form. Everything a form sends is a
string ("4", "yes", "  HeadPhones "), while the steps want numbers, booleans,
clean text and even loaded data. `Parse` bridges that gap, right next to the
parameter it applies to:

    limit: Annotated[int, Parse(int)] = 3     one parameter
    type Money = Annotated[Decimal, Parse(Decimal)]
                                              named once, reused in many steps
    type Text = Annotated[str, Parse(str.strip), Parse(str.lower)]
                                              several parsers, left to right
    **fields: Text                            every extra keyword
    type Names = Annotated[frozenset[str], Parse(load_names)]
                                              the form sends a path, the step gets the data

Parsing happens when the flow is built, so a bad value fails before anything runs.

Run it with `uv run python -m examples.parsing`.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated

from pyflowstep import FlowCompiler, Parse, ParseArgumentError, StepsRegistry, get_step_json_schema


@dataclass(frozen=True, slots=True)
class Product:
    name: str
    brand: str
    category: str
    price: Decimal
    stars: float
    in_stock: bool


type Catalog = tuple[Product, ...]

# Stands in for the file system, to keep the example self-contained.
FILES = {"discontinued.txt": "Travel Headphones\nKids Headphones\n"}


def parse_bool(text: str) -> bool:
    """Read checkbox-like values: yes/no, true/false, on/off, 1/0."""
    return text.strip().lower() in {"yes", "true", "on", "1"}


def load_names(path: str) -> frozenset[str]:
    """Read one product name per line from a file."""
    return frozenset(line.strip().lower() for line in FILES[path].splitlines())


# Parsed types, named once and reused by the steps below.
type Money = Annotated[Decimal, Parse(Decimal)]
type Text = Annotated[str, Parse(str.strip), Parse(str.lower)]
type Names = Annotated[frozenset[str], Parse(load_names)]

catalog_steps = StepsRegistry[Catalog]()


# 1. No marker: the value reaches the step exactly as it was given.
@catalog_steps.step()
def in_category(products: Catalog, category: str) -> Catalog:
    """Keep products of one category."""
    return tuple(product for product in products if product.category == category)


# 2. An alias used twice: both arguments become a Decimal.
@catalog_steps.step()
def price_between(products: Catalog, low: Money, high: Money) -> Catalog:
    """Keep products whose price is within [low, high]."""
    return tuple(product for product in products if low <= product.price <= high)


# 3. One marked parameter: `by` stays a plain string, the default 3 is not parsed.
@catalog_steps.step()
def top(products: Catalog, by: str, limit: Annotated[int, Parse(int)] = 3) -> Catalog:
    """Keep the `limit` best products by a numeric field."""
    return tuple(sorted(products, key=lambda product: getattr(product, by), reverse=True)[:limit])


# 4. Chained parsers: `Text` strips, then lowercases.
@catalog_steps.step()
def search(products: Catalog, text: Text, min_stars: Annotated[float, Parse(float)] = 0) -> Catalog:
    """Keep well-rated products whose name contains `text`."""
    return tuple(
        product
        for product in products
        if text in product.name.lower() and product.stars >= min_stars
    )


# 5. On `**fields` the parser applies to every extra keyword.
@catalog_steps.step()
def where(
    products: Catalog,
    *,
    in_stock: Annotated[bool, Parse(parse_bool)] = False,
    **fields: Text,
) -> Catalog:
    """Keep products matching every given text field, e.g. brand="sonic"."""
    return tuple(
        product
        for product in products
        if (product.in_stock or not in_stock)
        and all(getattr(product, key).lower() == value for key, value in fields.items())
    )


# 6. The form sends a path; the step receives the names loaded from that file.
@catalog_steps.step()
def exclude(products: Catalog, names: Names) -> Catalog:
    """Drop the products listed in a file."""
    return tuple(product for product in products if product.name.lower() not in names)


CATALOG: Catalog = (
    Product("Studio Headphones", "Sonic", "audio", Decimal("149.00"), 4.7, in_stock=True),
    Product("Travel Headphones", "Sonic", "audio", Decimal("89.00"), 4.2, in_stock=True),
    Product("Budget Headphones", "Sonic", "audio", Decimal("19.00"), 3.1, in_stock=True),
    Product("Pro Headphones", "Sonic", "audio", Decimal("349.00"), 4.9, in_stock=True),
    Product("Kids Headphones", "Sonic", "audio", Decimal("39.00"), 4.4, in_stock=False),
    Product("Bass Headphones", "Boom", "audio", Decimal("129.00"), 4.6, in_stock=True),
    Product("Desk Lamp", "Lumen", "home", Decimal("45.00"), 4.8, in_stock=True),
)

# What the web form sends: every value is a raw, untrimmed string.
FORM_FILTERS = [
    {"name": "in_category", "args": ["audio"]},
    {"name": "search", "args": ["  HeadPhones "], "kwargs": {"min_stars": "4"}},
    {"name": "where", "kwargs": {"in_stock": "yes", "brand": " SONIC "}},
    {"name": "exclude", "args": ["discontinued.txt"]},
    {"name": "price_between", "args": ["20", "400"]},
    {"name": "top", "kwargs": {"by": "stars", "limit": "2"}},
]


def main() -> None:
    compiler = FlowCompiler(catalog_steps.steps)
    filters = compiler.compile(FORM_FILTERS)  # type: ignore[arg-type]

    print(filters)
    for product in filters(CATALOG):
        print(f"{product.name} ({product.brand}) ${product.price} {product.stars}*")

    # The schema describes what the form must send: a path, not a set of names.
    schema = get_step_json_schema("exclude", catalog_steps["exclude"])
    print(f"exclude expects: {schema['properties']['args']['prefixItems']}")

    # A bad value fails while the flow is being built, with the place it came from.
    try:
        compiler.compile(
            [{"name": "in_category", "args": ["audio"]}, {"name": "top", "args": ["stars", "two"]}]
        )
    except ParseArgumentError as error:
        print(f"ParseArgumentError: {error} ({error.__notes__[0]})")


if __name__ == "__main__":
    main()
