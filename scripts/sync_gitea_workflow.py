#!/usr/bin/env python3
"""Regenerate `.gitea/workflows/test.yml` from `.github/workflows/test.yml`.

The two files have to exist separately, and it is worth writing down why,
because it is not obvious and it is NOT true of every repo in this family:

* Gitea does not read both workflow directories. It walks a candidate list
  and stops at the FIRST that exists - `.gitea/workflows`, then
  `.github/workflows` (go-gitea/gitea, `modules/actions/workflows.go`,
  `listWorkflowsInDirs`: ``if err == nil { break }``).
* `sync-wiki.yml` uses ``on: wiki``, a Gitea-only trigger, so it HAS to live
  in `.gitea/workflows/`. That one file makes the directory exist, which
  switches Gitea to it exclusively - and with no `test.yml` beside it, Gitea
  would run the wiki sync and no tests at all.
* Repos with no Gitea-only workflow (ostinato) need no copy: Gitea falls
  through to `.github/workflows` by itself.

**A symlink does not work.** Gitea filters entries by `.yml`/`.yaml` suffix
with no type check, so it *does* pick a symlink up - and then reads the
blob, which for a symlink is the target PATH, not the file. The path parses
as a YAML string rather than a mapping, so Gitea sees a workflow with no
jobs: it looks configured and runs nothing. Verified against a real git
repository, not assumed.

So the copy is necessary. This script makes it generated rather than
maintained, which is the difference between a duplication that drifts and
one that cannot.

Usage:
    python scripts/sync_gitea_workflow.py            # rewrite if stale
    python scripts/sync_gitea_workflow.py --check    # exit 1 if stale
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SOURCE = REPO / ".github" / "workflows" / "test.yml"
TARGET = REPO / ".gitea" / "workflows" / "test.yml"

HEADER = """# GENERATED FILE - do not edit. Run scripts/sync_gitea_workflow.py.
#
# A copy of .github/workflows/test.yml, byte-identical below this header.
# tests/test_ci_gates.py asserts that, so the two cannot drift.
#
# WHY THE DUPLICATION IS NECESSARY (not obvious, and not the case for every
# repo in this family - ostinato needs no .gitea copy):
#
# Gitea does not read both workflow directories. It walks a candidate list
# and stops at the FIRST that exists - `.gitea/workflows`, then
# `.github/workflows` (go-gitea/gitea, modules/actions/workflows.go,
# `listWorkflowsInDirs`: `if err == nil { break }`).
#
# `sync-wiki.yml` uses `on: wiki`, a Gitea-only trigger, so it HAS to live
# in `.gitea/workflows/`. That single file makes the directory exist, which
# switches Gitea to it exclusively - and without this copy beside it, Gitea
# would run the wiki sync and no tests whatsoever.
#
# A symlink does NOT work here: Gitea filters by filename suffix with no
# type check, so it reads the symlink's blob - which is the target path -
# and parses it as the workflow. The result is a workflow with no jobs that
# silently runs nothing.
#
# The same mechanism is why hassfest.yml and hacs.yml deliberately have no
# copy here: Gitea therefore never attempts them, which is what we want.
# Both drive GitHub-hosted actions (home-assistant/actions/hassfest,
# hacs/action) that expect a GitHub API and token, so on a Gitea runner they
# would fail for reasons that have nothing to do with the code.
"""


def render() -> str:
    """What `.gitea/workflows/test.yml` should contain."""
    return HEADER + SOURCE.read_text(encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if the copy is stale, without writing it",
    )
    args = parser.parse_args()

    if not SOURCE.is_file():
        print(f"FAIL: {SOURCE.relative_to(REPO)} does not exist")
        return 1

    expected = render()
    current = TARGET.read_text(encoding="utf-8") if TARGET.is_file() else None

    if current == expected:
        print(f"OK: {TARGET.relative_to(REPO)} is current")
        return 0

    if args.check:
        print(f"FAIL: {TARGET.relative_to(REPO)} is stale. Run scripts/sync_gitea_workflow.py.")
        return 1

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(expected, encoding="utf-8")
    print(f"regenerated {TARGET.relative_to(REPO)} from {SOURCE.relative_to(REPO)}")
    # Fails like a formatter does, so the regenerated file gets staged on the
    # next commit rather than being silently left behind.
    return 1


if __name__ == "__main__":
    sys.exit(main())
