from pyvocabulary import validate_name

from .exceptions import InvalidStepNameError


def validate_step_name(name: str) -> str:
    """Return `name` unchanged if it is a valid ASCII Python identifier.

    Example:
    ```python
    >>> validate_step_name("add_milk")
    'add_milk'
    >>> validate_step_name("add-milk")
    Traceback (most recent call last):
    ...
    pyflowstep.exceptions.InvalidStepNameError: Invalid step name: 'add-milk', ...

    ```

    """
    return validate_name(name, error=_invalid_step_name)


def _invalid_step_name(name: object) -> InvalidStepNameError:
    return InvalidStepNameError(
        f"Invalid step name: {name!r}, "
        "you should follow the python variable naming convention: "
        "name must start with a letter and can only contain letters, numbers and underscores"
    )
