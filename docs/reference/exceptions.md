# Exceptions

```text
Exception
├── PyflowstepError
│   ├── StepAlreadyRegisteredError
│   ├── StepDoesNotExistError                (also a LookupError)
│   ├── InvalidStepError                     (also a TypeError)
│   ├── InvalidDependencyError               (also a TypeError)
│   ├── InvalidInputError                    (also a TypeError)
│   ├── MissingInputError                    (also a TypeError)
│   ├── InvalidStepNameError                 (also a ValueError)
│   ├── InvalidFlowDefinitionError           (also a ValueError)
│   ├── UnsupportedFlowFormatError           (also a ValueError)
│   └── ArgumentError                        (also a TypeError)
│       ├── MissingArgumentError
│       ├── TooManyArgumentsError
│       ├── UnexpectedKeywordArgumentError
│       ├── MultipleValuesArgumentError
│       └── PositionalOnlyArgumentError
└── PyargprocessorsError                     (from pyargprocessors)
    ├── ProcessArgumentError                 (also a TypeError)
    └── InvalidProcessorError                (also a TypeError)
```

Argument processing belongs to pyargprocessors, so its two errors do not derive from
`PyflowstepError`. To catch everything a JSON flow can cause, catch both bases:

```python
from pyargprocessors import ProcessArgumentError, PyargprocessorsError

from pyflowstep import (
    ArgumentError,
    InvalidFlowDefinitionError,
    MissingInputError,
    PyflowstepError,
    StepDoesNotExistError,
)

assert issubclass(StepDoesNotExistError, LookupError)
assert issubclass(ArgumentError, TypeError) and issubclass(ArgumentError, PyflowstepError)
assert issubclass(MissingInputError, TypeError)
assert issubclass(InvalidFlowDefinitionError, ValueError)
assert issubclass(ProcessArgumentError, PyargprocessorsError)
assert not issubclass(ProcessArgumentError, PyflowstepError)
```

## When each one is raised

### While defining steps (your code, at import time)

| Exception | Cause |
| --- | --- |
| `InvalidStepError` | the function does not take the subject positionally; it is already a step factory; a bad `override` or `chain` |
| `InvalidDependencyError` | a misplaced `Depends`, a provider that is not callable, circular, or has a required non-dependency parameter |
| `InvalidInputError` | a misplaced `Input()`, a stub that does not match `Flow.signature`, an invalid output name |
| `InvalidProcessorError` | a misplaced or non-callable `Process`, or one combined with `Depends`/`Input` |
| `InvalidStepNameError` | a registry name that is not an ASCII identifier |
| `StepAlreadyRegisteredError` | a taken registry name |

These are programming errors: let them crash in development.

### While building or compiling a flow (often user input)

| Exception | Cause | Example message |
| --- | --- | --- |
| `MissingArgumentError` | a required argument is missing | `missing a required argument: 'selector' for step 'click'` |
| `TooManyArgumentsError` | too many positional arguments | `too many positional arguments for step 'click'` |
| `UnexpectedKeywordArgumentError` | an undeclared keyword | `got an unexpected keyword argument 'selctor' for step 'click'` |
| `MultipleValuesArgumentError` | given positionally and by keyword | `multiple values for argument 'selector' for step 'click'` |
| `PositionalOnlyArgumentError` | a positional-only parameter by keyword | `got some positional-only arguments passed as keyword arguments: width for step 'pad'` |
| `ProcessArgumentError` | a `Process` function raised | `Argument 'day' with value 'x' failed to process, ...` |
| `StepDoesNotExistError` | an unknown or hidden step name | `Step 'clik' does not exist. Available steps: click, fill` |
| `InvalidFlowDefinitionError` | a malformed definition or file | `Invalid step at $[0]: unknown keys ['selector'], ...` |
| `UnsupportedFlowFormatError` | a file suffix with no parser | `Unsupported flow file format '.xml'. Supported formats: .json, .toml` |

Catch them when compiling, and show the message with its notes.

### While running a flow

| Exception | Cause |
| --- | --- |
| `MissingInputError` | a required run input was not given, raised before the first step runs |
| anything else | raised by your steps or providers, unchanged |

## Notes

Errors raised while compiling get
[exception notes](https://docs.python.org/3/library/exceptions.html#BaseException.add_note):
`at $[i]` for the step, and `in <path>` when compiling a file. Read them from
`error.__notes__`.
