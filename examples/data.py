from typing import Any

from pyflowstep import compose, step, tap

type Data = list[dict[str, Any]]


@step
def filter_by_name(data: Data, *, endswith: str) -> Data:
    return [item for item in data if item["name"].endswith(endswith)]


@step
def filter_by_age_gt(data: Data, age: int) -> Data:
    return [item for item in data if item["age"] > age]


@step
def sort_by(data: Data, *, key: str, ascending: bool = True) -> Data:
    return sorted(data, key=lambda item: item[key], reverse=not ascending)


@tap
def log(data: Data) -> None:
    print(len(data))


DATA = [
    {"name": "Alice", "age": 20},
    {"name": "Bob", "age": 30},
    {"name": "Charlie", "age": 40},
    {"name": "David", "age": 50},
    {"name": "Eve", "age": 60},
    {"name": "Frank", "age": 70},
    {"name": "George", "age": 80},
]


def main() -> None:
    make_data = compose(
        log(),
        filter_by_age_gt(30),
        log(),
        sort_by(key="age", ascending=False),
        log(),
        filter_by_name(endswith="e"),
        log(),
    )
    make_data(DATA)


if __name__ == "__main__":
    main()
