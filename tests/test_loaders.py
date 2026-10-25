from pathlib import Path

import pytest

from pyflowstep import (
    FlowCompiler,
    InvalidFlowDefinitionError,
    StepDoesNotExistError,
    UnsupportedFlowFormatError,
    load_flow_definition,
    loaders,
    register_flow_format,
    step,
)


@step
def add(total: int, amount: int) -> int:
    return total + amount


@step
def multiply(total: int, factor: int) -> int:
    return total * factor


compiler = FlowCompiler[int]({"add": add, "multiply": multiply})

JSON_FLOW = '[{"name": "add", "args": [2]}, {"name": "multiply", "kwargs": {"factor": 10}}]'
TOML_FLOW = """
[[steps]]
name = "add"
args = [2]

[[steps]]
name = "multiply"
kwargs = { factor = 10 }
"""


def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


class TestBuiltinFormats:
    def test_json_and_toml_compile_to_the_same_flow(self, tmp_path: Path) -> None:
        from_json = compiler.compile_file(write(tmp_path, "flow.json", JSON_FLOW))
        from_toml = compiler.compile_file(write(tmp_path, "flow.toml", TOML_FLOW))
        assert from_json(1) == from_toml(1) == 30

    def test_suffix_is_case_insensitive(self, tmp_path: Path) -> None:
        assert compiler.compile_file(str(write(tmp_path, "flow.TOML", TOML_FLOW)))(1) == 30

    def test_toml_without_steps_is_rejected(self, tmp_path: Path) -> None:
        path = write(tmp_path, "flow.toml", 'name = "add"\n')
        with pytest.raises(InvalidFlowDefinitionError, match=r"\[\[steps\]\]") as info:
            load_flow_definition(path)
        assert f"in {path}" in info.value.__notes__

    @pytest.mark.parametrize(("name", "text"), [("flow.json", "[{"), ("flow.toml", "[[steps")])
    def test_malformed_file_is_rejected(self, tmp_path: Path, name: str, text: str) -> None:
        path = write(tmp_path, name, text)
        with pytest.raises(InvalidFlowDefinitionError, match="Invalid flow file") as info:
            load_flow_definition(path)
        assert str(path) in str(info.value)

    def test_step_error_points_to_the_file_and_step(self, tmp_path: Path) -> None:
        path = write(tmp_path, "flow.json", '[{"name": "add", "args": [1]}, {"name": "nope"}]')
        with pytest.raises(StepDoesNotExistError) as info:
            compiler.compile_file(path)
        assert info.value.__notes__ == ["at $[1]", f"in {path}"]


class TestRegistry:
    def test_unknown_suffix_lists_supported_formats(self, tmp_path: Path) -> None:
        with pytest.raises(UnsupportedFlowFormatError, match=r"'\.yaml'.*\.json, \.toml"):
            load_flow_definition(write(tmp_path, "flow.yaml", "- name: add"))

    def test_registered_format_is_used(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(loaders, "_PARSERS", dict(loaders._PARSERS))  # noqa: SLF001
        register_flow_format(".LINES", lambda text: [{"name": n} for n in text.split()])
        path = write(tmp_path, "flow.lines", "add")
        assert load_flow_definition(path) == [{"name": "add"}]

    def test_suffix_needs_a_dot(self) -> None:
        with pytest.raises(ValueError, match="must start with a dot"):
            register_flow_format("yaml", str.split)
