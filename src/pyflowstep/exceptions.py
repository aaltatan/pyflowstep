"""Exceptions raised by pyflowstep.

Every exception derives from `PyflowstepError`, so callers can catch the whole
family at once. Argument errors additionally derive from `TypeError`, and
definition errors from `ValueError`, to stay compatible with code that expects
the built-in exception types.
"""

import re
from collections.abc import Iterable


class PyflowstepError(Exception):
    """Base class for every exception raised by pyflowstep."""


class StepAlreadyRegisteredError(PyflowstepError):
    """Raised when a step name is registered twice in the same registry."""

    def __init__(self, name: str) -> None:
        super().__init__(f"Step '{name}' is already registered.")


class StepDoesNotExistError(PyflowstepError, LookupError):
    """Raised when a step name cannot be found in a registry or a compiler."""

    def __init__(self, name: str, available_steps: Iterable[str] | None = None) -> None:
        msg = f"Step '{name}' does not exist."

        if available_steps is not None:
            msg += f" Available steps: {', '.join(sorted(available_steps)) or '(none)'}"

        super().__init__(msg)


class InvalidStepError(PyflowstepError, TypeError):
    """Raised when a function cannot be turned into a step.

    A step function must accept the flow subject as its first positional
    parameter, for example `def click(page: Page, selector: str) -> Page`.
    """


class InvalidDependencyError(PyflowstepError, TypeError):
    """Raised when a `Depends(...)` declaration cannot work.

    For example a provider that is not callable, is circular, or has a required
    parameter that is not itself a dependency.
    """


class InvalidParserError(PyflowstepError, TypeError):
    """Raised when a `Parse(...)` marker cannot work.

    For example a parser that is not callable, a marker on the subject, or a
    marker used as a default value instead of inside `Annotated`.
    """


class InvalidStepNameError(PyflowstepError, ValueError):
    """Raised when a step name does not follow the Python identifier convention."""


class InvalidFlowDefinitionError(PyflowstepError, ValueError):
    """Raised when a flow definition (a list of step dictionaries) is malformed."""


class ArgumentError(PyflowstepError, TypeError):
    """Base class for errors caused by the arguments given to a step."""


class MissingArgumentError(ArgumentError):
    """Raised when a required step argument is missing."""


class TooManyArgumentsError(ArgumentError):
    """Raised when a step receives more positional arguments than it accepts."""


class UnexpectedKeywordArgumentError(ArgumentError):
    """Raised when a step receives a keyword argument it does not declare."""


class MultipleValuesArgumentError(ArgumentError):
    """Raised when a step argument is given both positionally and by keyword."""


class PositionalOnlyArgumentError(ArgumentError):
    """Raised when a positional-only step argument is passed as a keyword."""


class ParseArgumentError(ArgumentError):
    """Raised when a `Parse` function fails on the value given for a step argument."""


_ARGUMENT_ERROR_PATTERNS: tuple[tuple[str, type[ArgumentError]], ...] = (
    (r"positional.only.*passed as (a )?keyword", PositionalOnlyArgumentError),
    (r"missing a required", MissingArgumentError),
    (r"too many positional arguments", TooManyArgumentsError),
    (r"got an unexpected keyword argument", UnexpectedKeywordArgumentError),
    (r"multiple values for argument", MultipleValuesArgumentError),
)


def to_argument_error(error: TypeError, step_name: str) -> ArgumentError:
    """Translate a `Signature.bind` `TypeError` into the matching `ArgumentError`.

    Example:
    ```python
    >>> error = to_argument_error(TypeError("too many positional arguments"), "click")
    >>> type(error).__name__
    'TooManyArgumentsError'
    >>> str(error)
    "too many positional arguments for step 'click'"

    ```

    """
    message = str(error)
    error_type = next(
        (error for pattern, error in _ARGUMENT_ERROR_PATTERNS if re.search(pattern, message)),
        ArgumentError,
    )
    return error_type(f"{message} for step '{step_name}'")
