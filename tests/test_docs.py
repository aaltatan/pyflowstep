"""Run every ```python block of the documentation, so the examples cannot rot.

Blocks of one page run in order in one namespace, like a reader pasting them into
a single file. Fragments that cannot run on their own (Django, third-party
packages) are fenced as ```py instead, which is highlighted the same way.
"""

import re
from pathlib import Path

import pytest

DOCS = Path(__file__).parent.parent / "docs"
PYTHON_BLOCK = re.compile(r"^```python[^\n]*\n(.*?)^```", re.MULTILINE | re.DOTALL)
PAGES = sorted(DOCS.rglob("*.md"))


@pytest.mark.parametrize("page", PAGES, ids=[str(p.relative_to(DOCS)) for p in PAGES])
def test_page_examples_run(page: Path) -> None:
    namespace: dict[str, object] = {"__name__": f"docs.{page.stem}"}

    for number, block in enumerate(PYTHON_BLOCK.findall(page.read_text("utf-8")), 1):
        code = compile(block, f"{page.name}[block {number}]", "exec")

        exec(code, namespace)  # noqa: S102
