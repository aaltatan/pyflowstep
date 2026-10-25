"""Load flow definitions from files, picking a parser by file suffix.

Parsers are kept in a registry keyed by suffix. JSON (`.json`, a list of steps)
and TOML (`.toml`, `[[steps]]` tables) are built in; other formats are one
`register_flow_format` call away:

```python
>>> register_flow_format(".lines", lambda text: [{"name": n} for n in text.split()])
>>> _PARSERS[".lines"]("push pop")
[{'name': 'push'}, {'name': 'pop'}]
>>> del _PARSERS[".lines"]

```

A YAML parser, for example, is `register_flow_format(".yaml", yaml.safe_load)`.
"""

import json
import os
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .exceptions import InvalidFlowDefinitionError, UnsupportedFlowFormatError

type FlowParser = Callable[[str], Any]
"""Turn the text of a flow file into a flow definition (a list of step dictionaries)."""


def _parse_toml(text: str) -> Any:
    data = tomllib.loads(text)
    if "steps" not in data:
        msg = "Invalid flow definition: a TOML flow needs [[steps]] tables"
        raise InvalidFlowDefinitionError(msg)
    return data["steps"]


_PARSERS: dict[str, FlowParser] = {".json": json.loads, ".toml": _parse_toml}


def register_flow_format(suffix: str, parser: FlowParser) -> None:
    """Register `parser` for flow files ending in `suffix` (e.g. `".yaml"`).

    Suffixes are case-insensitive. Registering a suffix again replaces its parser.

    Raises:
        ValueError: If `suffix` does not start with a dot.

    """
    if not suffix.startswith("."):
        msg = f"A flow file suffix must start with a dot, received {suffix!r}"
        raise ValueError(msg)
    _PARSERS[suffix.lower()] = parser


def load_flow_definition(path: str | os.PathLike[str]) -> Any:
    """Read the flow file at `path` with the parser registered for its suffix.

    The result is unvalidated; `FlowCompiler.compile` checks it.

    Raises:
        UnsupportedFlowFormatError: If no parser is registered for the suffix.
        InvalidFlowDefinitionError: If the file cannot be parsed.

    """
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix not in _PARSERS:
        raise UnsupportedFlowFormatError(suffix, _PARSERS)

    try:
        return _PARSERS[suffix](path.read_text(encoding="utf-8"))
    except InvalidFlowDefinitionError as error:
        error.add_note(f"in {path}")
        raise
    except ValueError as error:  # JSONDecodeError and TOMLDecodeError are ValueErrors
        msg = f"Invalid flow file {path}: {error}"
        raise InvalidFlowDefinitionError(msg) from error
