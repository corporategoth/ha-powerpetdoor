# Testing Gaps Report

This file is **auto-generated** by CI after each test run. Do not edit manually.

**Last updated:** 2026-08-26 03:37 UTC

## Summary

| Metric | Value |
|--------|-------|
| Line Coverage | 100.00% |
| Branch Coverage | 100.00% |
| Lines Covered | 892 / 892 |
| Branches Covered | 170 / 170 |
| Lines Missing | 0 |

## Coverage by Category

| Category | Files | Coverage | Status |
|----------|-------|----------|--------|
| Core Library | 17 | 100.0% | :green_circle: |

## Status: 100% Coverage :green_circle:

All code is covered by tests. No gaps to report.

## Coverage Exclusions

### Gate Configuration

What the 100% gate measures, read from `pyproject.toml` (`tests/test_ci_gates.py` asserts each value):

- Measured roots (`coverage.run.source`): `custom_components/powerpetdoor`
- Branch coverage (`coverage.run.branch`): `true`
- Gate threshold (`coverage.report.fail_under`): `100`

### Automatic Exclusions

The following are excluded from coverage by configuration (`pyproject.toml`):

- `#\s*pragma:\s*no\s+cover\s*($|\()` - Explicitly annotated lines (see Pragma Exclusions below)
- `^\s*def __repr__` - String representation methods
- `^\s*raise NotImplementedError` - Abstract method stubs
- `^\s*if TYPE_CHECKING:` - Type-checking-only imports
- `^\s*if __name__ == .__main__.:` - Script entry-point guards
- `^\s*@overload\s*$` - Typing overload declarations
- `(^\s*\.\.\.\s*$)|(:\s*\.\.\.\s*$)` - Ellipsis stub bodies
- `#\s*pragma:\s*no\s+branch\s*($|\()` - Explicitly annotated partial branches (see Pragma Exclusions below)

### Acknowledged Gaps

Branches knowingly left uncovered. These are NOT configuration exclusions - the gate still counts them - and each one is a claim that the branch cannot be reached, with the reason why:

- **www/powerpetdoor-schedule-card.js - t(), the `if (!text) text = key`**
  Unreachable from any input. Every `t()` call site passes a literal key, and `scripts/check_translations.py` fails the build on a key that is not in the table, so no user action and no device response can reach it. Kept because the alternative when it IS wrong is rendering `undefined` into the card, which is worse for the user than showing the key.

### Prose-Triggered Exclusions

None. Every `exclude_lines` and `partial_branches` pattern above matches only the construct it names, never a string literal on a line carrying a statement.

### Pragma Exclusions

No `# pragma: no cover` or `# pragma: no branch` annotations found.
