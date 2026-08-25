#!/usr/bin/env python3
"""Write `.github/ha-matrix.json`'s grid into the workflow as a STATIC matrix.

The grid is measured, not declared (`scripts/ha_matrix.py`), so the workflow
must not hardcode it by hand. The obvious way to keep it honest is to read
the JSON at run time and fan out over it:

    matrix: ${{ fromJSON(needs.matrix.outputs.matrix) }}

**That does not work on Gitea, and it fails in two different ways.** Spelled
`matrix.include:`, Gitea's static parse - which runs when the Actions unit
is toggled on, and again on every push - reaches an unchecked type assertion
in act's `Job.GetMatrixes()` with a string where a list of maps is expected
and panics the request, which is an HTTP 500 on the settings page and no
Actions tab at all. Moved onto `matrix:` itself it parses, but the runner
never expands it: one job runs, named the literal `${{ matrix.name }}`, and
logs `'runs-on' key not defined` / `No steps found`. Four measured pairs
silently became one job that tested nothing.

A static matrix works on both forges, so the grid is expanded into the
workflow at authoring time instead and this script is what expands it.
`tests/test_ci_gates.py` asserts the expansion is current, so the two cannot
drift.

Usage:
    python scripts/expand_ci_matrix.py            # rewrite if stale
    python scripts/expand_ci_matrix.py --check    # exit 1 if stale
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MATRIX_FILE = REPO / ".github" / "ha-matrix.json"
WORKFLOW = REPO / ".github" / "workflows" / "test.yml"

#: The generated block, between these two markers. Anchored to whole lines so
#: a comment mentioning either phrase cannot be mistaken for a marker.
BEGIN = "      # >>> generated from .github/ha-matrix.json - do not edit by hand\n"
END = "      # <<< end generated matrix\n"

#: Keys copied into the workflow, in this order. `edge` is carried through
#: even though no step reads it: it is what makes a row legible in the CI
#: list ("is this the oldest HA on that interpreter, or the newest?").
FIELDS = ("name", "python-version", "homeassistant", "phacc", "edge")


def render(include: list[dict]) -> str:
    """The `matrix:` block exactly as it must appear in the workflow."""
    lines = [BEGIN, "      matrix:\n", "        include:\n"]
    for entry in include:
        prefix = "          - "
        for field in FIELDS:
            value = entry[field]
            lines.append(f'{prefix}{field}: "{value}"\n')
            prefix = "            "
    lines.append(END)
    return "".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 if stale")
    args = parser.parse_args()

    include = json.loads(MATRIX_FILE.read_text(encoding="utf-8"))["include"]
    if not include:
        print("FAIL: .github/ha-matrix.json has no entries", file=sys.stderr)
        return 1

    source = WORKFLOW.read_text(encoding="utf-8")
    pattern = re.compile(re.escape(BEGIN) + ".*?" + re.escape(END), re.S)
    if not pattern.search(source):
        print(f"FAIL: no generated matrix block in {WORKFLOW.relative_to(REPO)}", file=sys.stderr)
        return 1

    updated = pattern.sub(lambda _: render(include), source)
    if updated == source:
        print(f"OK: {WORKFLOW.relative_to(REPO)} matrix is current")
        return 0
    if args.check:
        print(
            f"FAIL: {WORKFLOW.relative_to(REPO)} matrix is stale - "
            "re-run scripts/expand_ci_matrix.py",
            file=sys.stderr,
        )
        return 1

    WORKFLOW.write_text(updated, encoding="utf-8")
    print(f"rewrote the matrix in {WORKFLOW.relative_to(REPO)} ({len(include)} entries)")
    print("now run scripts/sync_gitea_workflow.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
