# PHASES

## Round 1 — Agreed in the package-family review
- [x] Registry, JSON Schema and argument errors on pyvocabulary (branch `refactor/pyvocabulary`, 410 tests)
- [x] Step names with a trailing newline are rejected (bug in `re.match` with `$`)
- [ ] Open a draft PR for the branch until pyvocabulary is on PyPI

## Next
- [x] Not reproducible on Python 3.12.15 (passes on `main` and `refactor/pyvocabulary`, 2026-11-08). Original report: `tests/test_steps.py::TestArgumentValidation::test_positional_only_passed_by_keyword` it fails on `main` because 3.12 says "positional only" instead of "positional-only" (`requires-python` is `>=3.12`)
- [ ] Add Python 3.12 to CI so this cannot regress (there is no CI workflow yet; create one)
