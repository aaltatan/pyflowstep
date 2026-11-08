# PHASES

## Round 1 — Agreed in the package-family review
- [x] Registry, JSON Schema and argument errors on pyvocabulary (branch `refactor/pyvocabulary`, 410 tests)
- [x] Step names with a trailing newline are rejected (bug in `re.match` with `$`)
- [x] Open a draft PR for the branch. Merged into `main` locally for review instead of PRs; pyvocabulary 0.1.0 now comes from PyPI (2026-11-08)

## Next
- [x] Not reproducible on Python 3.12.15 (passes on `main` and `refactor/pyvocabulary`, 2026-11-08). Original report: `tests/test_steps.py::TestArgumentValidation::test_positional_only_passed_by_keyword` it fails on `main` because 3.12 says "positional only" instead of "positional-only" (`requires-python` is `>=3.12`)
- [x] Add Python 3.12 to CI so this cannot regress (`.github/workflows/ci.yml`: ruff, pyright, pytest with coverage on 3.12 and 3.13)
- [x] `override(original)`: a variant of a step with the same parameters and other defaults (stub decorator, registry form)
- [x] `chain` and `StepsRegistry.chain()`: a named step factory built from other steps, usable from JSON
- [ ] `output(name)` and `StepsRegistry.output()`: a step's return value becomes a run input for later steps, checked in order
