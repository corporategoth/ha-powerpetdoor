# Testing Gaps Report

This file is **auto-generated** by CI after each test run. Do not edit manually.

**Last updated:** 2026-08-25 20:18 UTC

## Summary

| Metric | Value |
|--------|-------|
| Line Coverage | 75.93% |
| Branch Coverage | 46.23% |
| Lines Covered | 607 / 758 |
| Branches Covered | 49 / 106 |
| Lines Missing | 151 |

## Coverage by Category

| Category | Files | Coverage | Status |
|----------|-------|----------|--------|
| Core Library | 16 (13 with gaps) | 80.1% | :yellow_circle: |

## Current Gaps (13 files)

| Module | Stmts | Missing | Coverage |
|--------|-------|---------|----------|
| `config_flow.py` | 71 | 44 | 32.5% |
| `websocket.py` | 81 | 47 | 34.0% |
| `select.py` | 54 | 26 | 42.4% |
| `diagnostics.py` | 10 | 2 | 80.0% |
| `tz_utils.py` | 14 | 1 | 87.5% |
| `number.py` | 41 | 5 | 88.4% |
| `schedule.py` | 114 | 8 | 89.0% |
| `coordinator.py` | 53 | 5 | 89.1% |
| `cover.py` | 41 | 3 | 92.7% |
| `button.py` | 30 | 2 | 93.3% |
| `binary_sensor.py` | 82 | 5 | 94.2% |
| `__init__.py` | 20 | 1 | 95.0% |
| `switch.py` | 71 | 2 | 97.2% |

### Missing Lines Detail

**`config_flow.py`**: 62, 69, 110-115, 117-119, 121, 126, 140, 144-147, 152-153, 155-157, 162, 164, 174-175, 177-179, 181-182, 184-186, 195, 197, 211-212, 216-217, 219, 221, 230

**`websocket.py`**: 78, 93-96, 99-101, 103, 105, 108-113, 118-119, 135-145, 161-163, 168-170, 188-190, 195-196, 198-203, 205

**`select.py`**: 76-78, 81-82, 87-89, 92-93, 99, 104, 108-110, 112-113, 115-117, 123-126, 132-133

**`diagnostics.py`**: 29-30

**`tz_utils.py`**: 53

**`number.py`**: 140-143, 148

**`schedule.py`**: 76, 136, 149, 188, 210, 282, 291, 294

**`coordinator.py`**: 133, 136-137, 174-175

**`cover.py`**: 97, 103-104

**`button.py`**: 100-101

**`binary_sensor.py`**: 202-204, 220-221

**`__init__.py`**: 68

**`switch.py`**: 308-309

## Coverage Exclusions

### Gate Configuration

What the 100% gate measures, read from `pyproject.toml` (`tests/test_gaps_report.py` asserts each value):

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
