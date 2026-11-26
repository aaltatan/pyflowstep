# Installation

pyflowstep needs **Python 3.12 or newer**.

=== "uv"

    ```bash
    uv add pyflowstep
    ```

=== "pip"

    ```bash
    pip install pyflowstep
    ```

It installs two small dependencies by the same author:

| Package | What pyflowstep uses it for |
| --- | --- |
| [pyargprocessors](https://github.com/aaltatan/pyargprocessors) | the `Process` marker that converts raw arguments |
| [pyvocabulary](https://pypi.org/project/pyvocabulary/) | the step registry and JSON Schema generation |

JSON and TOML flow files use the standard library. Other formats (YAML...) need their own
parser, see [Flow files](guide/compiling.md#other-formats).

## Check it works

```python
from pyflowstep import step


@step
def add(total: int, amount: int) -> int:
    return total + amount


assert (add(2) >> add(3))(10) == 15
```
