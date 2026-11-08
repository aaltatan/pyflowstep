# pyflowstep

Function composition as readable flows: `fill("#email", email) >> click("#submit")`, built from
`@step` functions, with dependencies, inputs, JSON compilation (`FlowCompiler`) and JSON
Schemas generated from step signatures.

## The family

Each package wraps `Callable[[T], R]` in an immutable value with an algebra, plus the
same supporting pieces: a decorator that turns functions into factories, arguments
bound at build time, a registry (the vocabulary), a JSON compiler with JSON-path
errors, and a JSON Schema generated from signatures.

| Package | Wraps | Composes with | Status |
| --- | --- | --- | --- |
| pyspecification | `T -> bool` | `&` `\|` `~` | released |
| pyformula | `T -> number` | arithmetic operators | released |
| pyflowstep | `T -> T` | `>>` | released |
| pyvocabulary | shared core: `Vocabulary`, JSON Schema, path notes | — | 0.1 built, not published |
| pyruleset | `T -> V`, first match wins | `\|` | 0.1 built, not published |
| pyordering | `T -> sort key` | `>>`, `~` | planned |
| pyaggregation | `Iterable[T] -> dict` | `&` | planned |
| pyprojection | `T -> dict` | `&` | planned |

All repositories live side by side in `~/dev/<name>` on the author's machine.

## Commands

```bash
uv sync                                   # create .venv with dev dependencies
uv run pytest                             # tests and doctests
uv run pytest --cov --cov-branch          # with branch coverage
uv run --python 3.12 pytest               # on the minimum supported version
uvx ruff check . && uvx ruff format --check .
uvx pyright src                           # strict type checking, no blanket ignores
```

The package is `pyflowstep` under `src/`, built with `uv_build`.

## Design rules for this package

- Flows are immutable and flat; `>>` returns a new flow.
- Registry, JSON Schema, path notes and argument-error classification come from
  pyvocabulary (branch `refactor/pyvocabulary`).
- pyflowstep is the orchestrator of the family: pyruleset can return a flow as its value.

## Code style (non-negotiable)

- Python 3.12+, PEP 695 generics (`class Ruleset[T, V]:`, `type Value[T, V] = Callable[[T], V]`).
- Simplest thing that works. No abstraction until a second real use exists.
- Functions first; a class only when it holds state or gives a nicer API (composable operators).
- Pure core, side effects at the edges. Composition over inheritance. No ABCs; use `Protocol`.
- Immutable values: `@dataclass(frozen=True, slots=True)`; operators return new objects.
- Fail early: validate when something is built, not when it runs.
- Full type hints, `collections.abc` imports, `Literal`/`TypedDict`/`Protocol` where they fit.
- `/` for positional-only, `*` for keyword-only (always for boolean flags).
- Guard clauses, `match`, comprehensions, walrus where it reads better. `pathlib`, never `os.path`.
- Errors: a package base exception, specific subclasses, message built before `raise`
  (ruff EM), `raise X from error` when translating. Messages say what is wrong and what
  is valid: "Rule 'foo' does not exist. Available rules: a, b, c".
- JSON-path context is added as an exception note via `pyvocabulary.located`, never
  by wrapping the error in another type.
- Google-style docstrings with runnable doctests in ```python blocks. Comment only the *why*.
- Public functions first, `_private` helpers below; `# ---` section comments in long modules.
- Tests: `class TestThing:` with behaviour-named methods, fixtures in `conftest.py`,
  `pytest.raises(..., match=...)`. Branch coverage on.
- Ask before adding a runtime dependency. Do not add features, options or layers nobody asked for.

## How to work here

1. Read `PHASES.md`. Work on the first unchecked item only.
2. Write the test first, then the code. Keep doctests runnable.
3. Before ticking a box, run the full check (commands above) on Python 3.12 and 3.13.
4. Tick the box in `PHASES.md` in the same commit as the work.
5. Small commits on a branch; never push or publish unless asked.

## Kickoff prompt for a new conversation

Paste this into a new Claude conversation linked to this computer:

> You are working on `pyflowstep` in `~/dev/pyflowstep`. Read `CLAUDE.md` and `PHASES.md` there
> first and follow them exactly. Continue with the next unchecked item. Work on a new git branch, run the full check on
> Python 3.12 and 3.13, tick what you finish in `PHASES.md`, and commit. Do not push or
> publish. When done, summarise what changed and what the next unchecked item is.

## Active plan (not started)

Agreed design, written down so the work can continue on another machine. Nothing below is
implemented yet. Start here: add its three items to `PHASES.md`, then follow "How to work here".
Do not bump the version unless asked.

### Step variants, registered chains and step outputs

### Context

Three gaps appear when building larger flows from small steps:

1. **Variant of a step**: same body and parameters, but a parameter becomes `Input()`.
2. **Chain**: a named step made of other steps, instead of `(a() >> b())(page)` inside a body.
   A plain function returning a `Flow` composes today, but it has no step-style argument errors or
   `Process`, and it cannot be registered for JSON.
3. **A later step needs a value from an earlier step**: the value should reach an ordinary
   `Input()`, so generic steps stay reusable and wrong order fails before the flow starts.

```python
@step
def fill_date(page: Page, *, value: datetime) -> Page: ...

@override(fill_date)
def fill_voucher_date(page: Page, *, value: datetime = Input()) -> Page: ...

@chain  # or @registry.chain() to use it from JSON
def submit_voucher(date_selector: str) -> Flow[Page]:
    return fill_date_at(date_selector) >> click("#save")

@output("number")
def read_number(page: Page) -> str:
    return page.text("#no")

@step
def fill(page: Page, selector: str, number: str = Input()) -> Page: ...

(read_number() >> fill("#target"))(page)   # number comes from read_number
```

Agreed scope: `override` requires the same parameter names and changes only defaults, no
renaming in this version. Three features, one commit series, in the order below.

### 1. `override(original)`

- Decorator on a stub whose body never runs; the original body does. A stub is used because
  `ParamSpec` cannot express "same parameters minus one".
- Arguments, `Input`, `Depends`, `Process`, schema and step name all come from the stub.
- Step, tap and output behaviour carry over from the original.
- Docstring is the stub's, or the original's when the stub has none.
- Override of an override runs the first real body, never a stub.

Rejected at build with `InvalidStepError`: `original` is not a step factory; parameters after
the subject differ in name, order or kind; a parameter with `Process` on the original has none
on the stub and is not injected (it would silently vanish).

### 2. `chain` and `StepsRegistry.chain(name=, description=, hidden=)`

- Decorates `(...build args) -> Flow[T]`. There is no subject parameter, every parameter is a
  build argument, and the returned flow stays flat so `Input`s of its steps reach `flow.inputs`.
- The factory binds with `bind_arguments` (so `ArgumentError` subclasses and JSON path notes work)
  and applies `Process` with `find_processors(fn, skip=0)`.
- Rejected with `InvalidStepError`: `Input` or `Depends` on a chain parameter (declare them on
  the steps), and a function that returns something other than a `Flow`.
- Two forms like `step` and `tap`: standalone `@chain` and `@registry.chain()`, the latter built on
  the former.

### 3. `output(name)` and `StepsRegistry.output(name, step_name=...)`

The registry method's first positional is the output name; its keyword `step_name` avoids the
clash: `registry.output("number", step_name=, description=, hidden=)`.

- The function's return value is stored in the run's inputs under `name`; the subject passes
  through unchanged, like `tap`.
- Reuses `Input` on the reading side with no change to steps that read it.
- The value lives in the current run scope. A nested flow called with its own inputs has an
  overlay scope, so what it outputs ends with it.
- A later output of the same name replaces the earlier one, and a produced value replaces a value
  the caller passed under that name, for steps after the producer.
- `name` must be a valid non-keyword identifier, else `InvalidInputError` at decoration.

Order-aware input checks, in one private generator in `inputs.py` that walks the actions and yields
each action's inputs not produced by an earlier action. It backs all three of:
- `check_inputs` (reading before producing is `MissingInputError` before the first step),
- `Flow.inputs` (produced names are not asked of the caller),
- `check_signature` (`Flow.signature` stubs do not declare produced names).

An action needing its own output still needs it from the caller, since it reads before it writes.

### Changes

`src/pyflowstep/inputs.py`: `mark_output` / `action_output` (same pattern as `mark_inputs`), the
generator above, and a function for `Flow.inputs`.

`src/pyflowstep/flow.py`: `inputs` property uses the new function.

`src/pyflowstep/dependencies.py`: `Run.inputs` typed `dict[str, Any]`, since outputs write to it.

`src/pyflowstep/steps.py`:
- `_make_step` gains `body=None` and `output=None`. Signature data is read from `fn`; `body or fn`
  runs. `_make_action` writes the output through `run_scope()`.
- The factory records a private frozen `_Origin(body, passthrough, output)`. Not `__wrapped__`:
  on an override that is the stub.
- New public `override`, `output`, `chain`; private `_check_override`.

`src/pyflowstep/registry.py`: `override`, `chain`, `output` methods. Extract the common part of
`register` (name validation, duplicate check, `_renamed`, doc, `add`) into one private method
taking the maker, so all paths behave the same.

`src/pyflowstep/__init__.py`: export `override`, `output`, `chain`.

`README.md`: rows in the Registry and API tables, plus the three example-led sections below. Every
example is complete code with its result or exact error shown, and is run once during
verification so the README cannot show something the code does not do.

`### override` (after `### tap`):
- the basic variant: a parameter becomes `Input()`, and how the flow is then called
- a parameter becomes `Depends(...)`, gets another plain default, or an `Input()` becomes an argument
- overriding a `tap` and an `output` step: the behaviour carries over
- several variants in one flow: keeping `value` shares one input, shown with its result, and the
  delegating one-line body as the way to get separate names
- `Process`: repeated on the stub to keep it; a value arriving through `Input` is not processed
- docstring inherited or replaced; step name in `repr` and errors; override of an override
- registry form with `name`, `description`, `hidden`, then used from JSON and shown in the schema
- each error: not a step factory, parameters differ, `Process` lost, positional-only as `Input`,
  duplicate registry name
- typing: why it is a stub, and what the type checker sees

`### Chains` (in Registry):
- no parameters (a `Flow` value), a plain function, standalone `@chain`, and `@registry.chain()`,
  with what each one adds over the one before
- chains inside chains and next to steps, staying flat in `repr`
- a chain's inputs are its steps': visible in `flow.inputs`, checked before the first step
- `Process` on a chain argument; used from JSON with `args` and `kwargs`; the JSON schema
- each error: bad arguments with the JSON path note, `Input` or `Depends` on a chain parameter,
  a function not returning a `Flow`, duplicate name
- when to use a chain and when a step that calls flows in its body

`### Outputs` (in Run inputs):
- the basic producer and reader; the subject passes through unchanged
- one output read by several steps; several outputs; optional `Input(default=...)` reader
- producer inside a chain; producer and reader from JSON; registry form
- reading before producing: the `MissingInputError`, raised before any step runs
- `flow.inputs` and `Flow.signature` leave out produced names
- a later output of the same name replaces the earlier one; a produced value against one passed
  by the caller; a step that needs its own output name
- no leak between runs; a nested flow with its own inputs keeps its outputs to itself
- an output step with its own `Input` and `Depends`; a producer returning `None`
- each error: invalid or keyword output name
- choosing between `Input`, `Depends` and outputs

`PHASES.md`: three items under `## Next`, each ticked in its own commit.

### Tests first (`tests/test_override.py`, `test_chain.py`, `test_outputs.py`)

- override: becomes `Input` / `Depends` / plain default; `Input` becomes argument; tap and output
  kept; stub not called; override of override; `Process` kept; docstring; name in errors; each
  rejection; registry path including JSON compile, schema, `hidden`, duplicate name.
- chain (standalone and registry): flat `repr`, inputs visible and checked before the first step, `ArgumentError` with JSON
  path note, `Process`, schema, `name` / `description` / `hidden`, both rejections.
- outputs: value reaches `Input`; subject unchanged; `flow.inputs` omits produced names; read
  before produce raises before any step runs; optional input takes the produced value; replaced by
  a later output; no leak between runs; nested overlay scope; `Flow.signature`; through a chain;
  through JSON; invalid names.

### Delivery

Work on the existing branch `feat/step-variants`. Small commits, push only when asked.

### Verification

```bash
uv run --python 3.12 pytest --cov --cov-branch
uv run --python 3.13 pytest --cov --cov-branch
uvx ruff check . && uvx ruff format --check .
uvx pyright src
```

Pyright must accept real stubs with `P` inferred, with no new blanket ignores.

Run every new README example once against the finished code and compare it with the output the
README shows.
