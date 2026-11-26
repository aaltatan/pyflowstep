# API

`T` is the type of the flow subject; `P` the parameters of a step after the subject.

## Flows

### `Flow[T]`

```py
Flow(*actions: Action[T])
```

An immutable sequence of actions applied in order to one subject.

| Member | Description |
| --- | --- |
| `flow(obj, /, **inputs) -> T` | run every action; `inputs` are the [run inputs](../guide/inputs.md); `MissingInputError` before the first action if a required one is missing |
| `a >> b`, `callable >> flow` | a new flat flow: the actions of the left side, then of the right side |
| `actions -> tuple[Action[T], ...]` | the actions, in order |
| `inputs -> frozenset[str]` | the run inputs the caller must give (not produced by an earlier [output](../guide/inputs.md#outputs)) |
| `signature(stub)` | decorator: a [typed call](../guide/inputs.md#typed-calls); `InvalidInputError` if `stub` does not match |
| `len(flow)`, `iter(flow)` | number of actions, iteration |
| `bool(flow)` | always `True` |
| `repr(flow)` | `Flow(step_a >> step_b)` |

### `compose`

```py
compose(*actions: Action[T]) -> Flow[T]
```

`Flow() >> a >> b >> ...`, flattened.

### `Action`

```py
type Action[T] = Callable[[T], T]
```

## Steps

### `step`

```py
step(fn: StepFn[T, P], /) -> StepFactory[T, P]
```

Turn `(subject, *args, **kwargs) -> subject` into a factory `(*args, **kwargs) -> Flow[T]`.
Raises `InvalidStepError` if `fn` does not take the subject positionally or is already a
step factory, `InvalidDependencyError` / `InvalidInputError` / `InvalidProcessorError` for
misplaced markers. The factory raises `ArgumentError` subclasses and
`ProcessArgumentError`.

### `tap`

```py
tap(fn: TapFn[T, P], /) -> StepFactory[T, P]
```

Like `step`; the return value is ignored and the subject passes through.

### `output`

```py
output(name: str, /) -> Callable[[TapFn[T, P]], StepFactory[T, P]]
```

Decorator: like `tap`, and the return value becomes the run input `name` for later steps.
`InvalidInputError` if `name` is not an identifier or is a keyword.

### `override`

```py
override(original: StepFactory[T, ...], /) -> Callable[[TapFn[T, P]], StepFactory[T, P]]
```

Decorator on a stub: a variant of `original` with the stub's name, docstring, defaults
and markers, running `original`'s body. `InvalidStepError` if `original` is not a step
factory, the parameters differ in name, order or kind, or a processed parameter loses its
`Process`.

### `chain`

```py
chain(fn: Callable[P, Flow[T]], /) -> StepFactory[T, P]
```

A factory that binds and processes its arguments like a step, then returns the flow `fn`
builds. `InvalidStepError` if a parameter is `Input()` or `Depends(...)`, or (when called)
if `fn` does not return a `Flow`.

### Type aliases

```py
type StepFn[T, **P] = Callable[Concatenate[T, P], T]
type TapFn[T, **P] = Callable[Concatenate[T, P], Any]
type StepFactory[T, **P] = Callable[P, Flow[T]]
```

## Markers

### `Depends`

```py
Depends(provider: Callable[..., Any], /) -> Any
```

Default value of a parameter injected by calling `provider` once per run. Providers may be
generator functions (cleaned up when the run ends) and may themselves use `Depends`.
`InvalidDependencyError` if `provider` is not callable.

### `override_dependencies`

```py
override_dependencies(overrides: Mapping[provider, provider]) -> ContextManager[None]
```

Replace providers inside a `with` block; nests, restores on exit.

### `Input`

```py
Input(*, default: Any = <required>) -> Any
```

Default value of a parameter supplied by the caller when the flow runs; optional when
`default` is given.

### `Process`

From pyargprocessors: `Annotated[T, Process(fn)]` applies `fn` to the argument when the
step is built. See [Arguments and processing](../guide/arguments.md).

## Registry

### `StepsRegistry[T]`

```py
StepsRegistry[T]()
```

| Member | Description |
| --- | --- |
| `step(*, name=None, description=None, hidden=False)` | decorator registering a step |
| `tap(*, name=None, description=None, hidden=False)` | decorator registering a tap |
| `output(input_name, /, *, step_name=None, description=None, hidden=False)` | decorator registering an output step |
| `override(original, /, *, name=None, description=None, hidden=False)` | decorator registering a variant |
| `chain(*, name=None, description=None, hidden=False)` | decorator registering a chain |
| `register(fn, /, *, name=None, description=None, hidden=False, passthrough=False)` | register an existing function; returns the factory |
| `registry[name]` | the factory; `StepDoesNotExistError` if unknown or hidden |
| `name in registry`, `iter(registry)`, `len(registry)` | the visible steps |
| `steps -> Mapping[str, StepFactory]` | read-only snapshot of the visible steps |

Registration raises `StepAlreadyRegisteredError` for a taken name (hidden ones included)
and `InvalidStepNameError` for a name that is not an ASCII identifier.

## Compiling

### `FlowCompiler[T]`

```py
FlowCompiler(steps: Mapping[str, Callable[..., Flow[T]]], /)
```

| Member | Description |
| --- | --- |
| `compile(definition: FlowDefinition) -> Flow[T]` | compile a list of step dictionaries; errors carry `at $[i]` notes |
| `compile_file(path) -> Flow[T]` | load by suffix and compile; errors also carry `in <path>` |

### `StepDict`, `FlowDefinition`

```py
class StepDict(TypedDict):
    name: str
    args: NotRequired[list[Any]]
    kwargs: NotRequired[dict[str, Any]]

type FlowDefinition = Sequence[StepDict]
```

### `validate_step_dict`

```py
validate_step_dict(item: Any, path: str = "$") -> StepDict
```

Return `item` if it is a well-formed step dictionary; `InvalidFlowDefinitionError`
otherwise.

### Flow files

| Name | Description |
| --- | --- |
| `load_flow_definition(path) -> Any` | parse a flow file by suffix, without compiling; `UnsupportedFlowFormatError`, `InvalidFlowDefinitionError` |
| `register_flow_format(suffix, parser)` | add or replace the parser of a suffix (case-insensitive, must start with a dot) |
| `FlowParser` | `type FlowParser = Callable[[str], Any]`: file text to step dictionaries |

Built-in formats: `.json` (a list of steps) and `.toml` (`[[steps]]` tables).

## JSON Schema

| Function | Returns |
| --- | --- |
| `get_flow_json_schema(steps: Mapping[str, Callable]) -> dict` | draft 2020-12 schema of a flow definition |
| `get_step_json_schema(name: str, step: Callable) -> dict` | schema of one step dictionary |
| `get_json_schema(annotation: Any) -> dict` | schema of one Python type |

## Exceptions

See [Exceptions](exceptions.md).
