"""Compose functions into readable, reusable, JSON-definable flows.

`pyflowstep` is a functional replacement for the fluent-interface (method chaining)
pattern. Instead of adding chainable methods to a class, you write small step
functions and compose them with `>>`:

```python
>>> from pyflowstep import step
>>> @step
... def add(total: int, amount: int) -> int:
...     return total + amount
>>> @step
... def double(total: int) -> int:
...     return total * 2
>>> (add(3) >> double() >> add(1))(0)
7

```

Steps collected in a `StepsRegistry` can also be described as JSON
(`get_flow_json_schema`) and compiled from JSON (`FlowCompiler`).

Raw JSON values become typed arguments with the `Process` marker of
`pyargprocessors`, written next to the parameter:

```python
>>> from typing import Annotated
>>> from pyargprocessors import Process
>>> @step
... def scale(total: int, factor: Annotated[int, Process(int)]) -> int:
...     return total * factor
>>> scale("3")(2)
6

```
"""

from .compilers import FlowCompiler, FlowDefinition, StepDict, validate_step_dict
from .dependencies import Depends, override_dependencies
from .exceptions import (
    ArgumentError,
    InvalidDependencyError,
    InvalidFlowDefinitionError,
    InvalidInputError,
    InvalidStepError,
    InvalidStepNameError,
    MissingArgumentError,
    MissingInputError,
    MultipleValuesArgumentError,
    PositionalOnlyArgumentError,
    PyflowstepError,
    StepAlreadyRegisteredError,
    StepDoesNotExistError,
    TooManyArgumentsError,
    UnexpectedKeywordArgumentError,
)
from .flow import Action, Flow, compose
from .inputs import Input
from .json_schema import get_flow_json_schema, get_json_schema, get_step_json_schema
from .registry import StepsRegistry
from .steps import StepFactory, StepFn, TapFn, step, tap

__all__ = [
    "Action",
    "ArgumentError",
    "Depends",
    "Flow",
    "FlowCompiler",
    "FlowDefinition",
    "Input",
    "InvalidDependencyError",
    "InvalidFlowDefinitionError",
    "InvalidInputError",
    "InvalidStepError",
    "InvalidStepNameError",
    "MissingArgumentError",
    "MissingInputError",
    "MultipleValuesArgumentError",
    "PositionalOnlyArgumentError",
    "PyflowstepError",
    "StepAlreadyRegisteredError",
    "StepDict",
    "StepDoesNotExistError",
    "StepFactory",
    "StepFn",
    "StepsRegistry",
    "TapFn",
    "TooManyArgumentsError",
    "UnexpectedKeywordArgumentError",
    "compose",
    "get_flow_json_schema",
    "get_json_schema",
    "get_step_json_schema",
    "override_dependencies",
    "step",
    "tap",
    "validate_step_dict",
]
