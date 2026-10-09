"""Browser automation: pyflowstep as a replacement for a fluent `Page` API.

`Page` is a mutable object with side-effect methods, so its steps are
registered with `tap`: they act on the page and hand it to the next step.

Run it with `uv run python -m examples.browser`.
"""

import json
from typing import Annotated, Any

from pyargprocessors import Process

from pyflowstep import FlowCompiler, StepsRegistry, compose, get_flow_json_schema


class Page:
    """A fake browser page that prints and records every action."""

    def __init__(self) -> None:
        self.history: list[str] = []

    def _record(self, action: str) -> None:
        self.history.append(action)
        print(action)

    def navigate(self, url: str) -> None:
        self._record(f"Navigating to {url}")

    def click(self, selector: str) -> None:
        self._record(f"Clicking on {selector}")

    def fill(self, selector: str, value: Any) -> None:
        self._record(f"Filling {selector} with {value}")

    def wait(self, selector: str, timeout: float = 5.0) -> None:
        self._record(f"Waiting for {selector} ({timeout}s)")


def https_only(url: str) -> str:
    """Processor: reject insecure urls before the flow ever runs."""
    if not url.startswith("https://"):
        msg = f"only https urls are allowed, got {url!r}"
        raise ValueError(msg)
    return url


page_steps = StepsRegistry[Page]()


@page_steps.tap()
def navigate(page: Page, url: Annotated[str, Process(https_only)]) -> None:
    """Open a url in the page."""
    page.navigate(url)


@page_steps.tap()
def click(page: Page, selector: str) -> None:
    """Click the element matching a CSS selector."""
    page.click(selector)


@page_steps.tap()
def fill(page: Page, selector: str, value: str | int) -> None:
    """Type a value into the field matching a CSS selector."""
    page.fill(selector, value)


@page_steps.tap()
def wait(page: Page, selector: str, timeout: Annotated[float, Process(float)] = 5.0) -> None:
    """Wait until an element matching a CSS selector appears."""
    page.wait(selector, timeout)


def main() -> None:
    # A reusable sub-flow, composed from Python.
    search_google = compose(
        navigate("https://www.google.com"),
        fill("input[name=q]", "pyflowstep"),
        click("input[type=submit]"),
        wait("div#result"),
    )

    compiler = FlowCompiler(page_steps.steps)
    login = compiler.compile(
        [
            {"name": "navigate", "args": ["https://example.com/login"]},
            {"name": "fill", "args": ["#email", "ada@example.com"]},
            {"name": "fill", "kwargs": {"selector": "#password", "value": "hunter2"}},
            {"name": "click", "args": ["button[type=submit]"]},
            {"name": "wait", "args": ["#dashboard"], "kwargs": {"timeout": "10"}},
        ]
    )

    page = Page()

    print("--- search (Python) ---")
    search_google(page)

    print("\n--- login (JSON) ---")
    login(page)

    print("\n--- login, then search: flows are just values ---")
    (login >> search_google >> wait("footer"))(page)

    print("\n--- JSON schema of the page language ---")
    print(json.dumps(get_flow_json_schema(page_steps.steps), indent=2)[:400], "...")


if __name__ == "__main__":
    main()
