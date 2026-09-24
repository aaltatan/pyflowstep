import pytest

from pyflowstep import (
    ArgumentError,
    InvalidFlowDefinitionError,
    InvalidStepError,
    InvalidStepNameError,
    MissingArgumentError,
    MultipleValuesArgumentError,
    PositionalOnlyArgumentError,
    ProcessArgumentError,
    PyflowstepError,
    StepAlreadyRegisteredError,
    StepDoesNotExistError,
    TooManyArgumentsError,
    UnexpectedKeywordArgumentError,
)
from pyflowstep.exceptions import to_argument_error
from pyflowstep.validators import validate_step_name


class TestHierarchy:
    @pytest.mark.parametrize(
        "error",
        [
            StepAlreadyRegisteredError,
            StepDoesNotExistError,
            InvalidStepError,
            InvalidStepNameError,
            InvalidFlowDefinitionError,
            ArgumentError,
        ],
    )
    def test_everything_is_a_pyflowstep_error(self, error: type[Exception]) -> None:
        assert issubclass(error, PyflowstepError)

    @pytest.mark.parametrize(
        "error",
        [
            MissingArgumentError,
            TooManyArgumentsError,
            UnexpectedKeywordArgumentError,
            MultipleValuesArgumentError,
            PositionalOnlyArgumentError,
            ProcessArgumentError,
        ],
    )
    def test_argument_errors(self, error: type[Exception]) -> None:
        assert issubclass(error, ArgumentError)
        assert issubclass(error, TypeError)

    def test_builtin_compatibility(self) -> None:
        assert issubclass(StepDoesNotExistError, LookupError)
        assert issubclass(InvalidStepNameError, ValueError)
        assert issubclass(InvalidFlowDefinitionError, ValueError)


class TestMessages:
    def test_step_already_registered(self) -> None:
        assert str(StepAlreadyRegisteredError("x")) == "Step 'x' is already registered."

    def test_step_does_not_exist(self) -> None:
        assert str(StepDoesNotExistError("x")) == "Step 'x' does not exist."
        assert str(StepDoesNotExistError("x", ["b", "a"])) == (
            "Step 'x' does not exist. Available steps: a, b"
        )


class TestToArgumentError:
    @pytest.mark.parametrize(
        ("message", "error"),
        [
            ("missing a required argument: 'a'", MissingArgumentError),
            ("missing a required keyword-only argument: 'a'", MissingArgumentError),
            ("too many positional arguments", TooManyArgumentsError),
            ("got an unexpected keyword argument 'a'", UnexpectedKeywordArgumentError),
            ("multiple values for argument 'a'", MultipleValuesArgumentError),
            (
                "'a' parameter is positional only, but was passed as a keyword",
                PositionalOnlyArgumentError,
            ),
            (
                "got some positional-only arguments passed as keyword arguments: 'a'",
                PositionalOnlyArgumentError,
            ),
            ("something new in a future python", ArgumentError),
        ],
    )
    def test_maps_messages_to_errors(self, message: str, error: type[ArgumentError]) -> None:
        converted = to_argument_error(TypeError(message), "step_name")
        assert type(converted) is error
        assert str(converted) == f"{message} for step 'step_name'"


class TestValidateStepName:
    @pytest.mark.parametrize("name", ["a", "_private", "snake_case", "CamelCase", "x1"])
    def test_valid(self, name: str) -> None:
        assert validate_step_name(name) == name

    @pytest.mark.parametrize("name", ["", "1x", "a-b", "a b", "a.b", "<lambda>", "café", 1, None])
    def test_invalid(self, name: object) -> None:
        with pytest.raises(InvalidStepNameError, match="Invalid step name"):
            validate_step_name(name)  # type: ignore[arg-type]
