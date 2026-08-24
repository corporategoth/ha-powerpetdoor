#!/usr/bin/env python3
"""Keep the Lovelace card's advertised version honest.

Home Assistant serves `www/` as `/local/` and browsers cache it hard. A user
who updates the integration and gets a stale card has no way to tell: the
dashboard renders, it just behaves like the old version. The version banner
the card prints on load is the only signal they have, so it has to mean
something.

Two failure modes, both observed in this repo:

1. **Internal drift.** The header comment said `v1.6.0` while the
   `console.info` banner said `v1.5.0`. Whichever a user reads, one of them
   was lying.
2. **Silent republish.** The card changed but neither version moved, so a
   cached copy and a fresh copy are indistinguishable.

Run with no arguments as a pre-push hook: it compares the working tree
against the upstream base and fails if the card moved without its version
moving.

Usage:
    python scripts/check_card_version.py            # vs. the merge base
    python scripts/check_card_version.py --base HEAD
    python scripts/check_card_version.py --consistency-only
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CARD = Path("www/powerpetdoor-schedule-card.js")

#: `* Power Pet Door Schedule Card v1.6.0` in the file header.
_HEADER = re.compile(r"Schedule Card\s+v(?P<version>\d+\.\d+\.\d+)")

#: `'%c POWERPETDOOR-SCHEDULE-CARD %c v1.5.0 '` in the console banner.
_BANNER = re.compile(r"POWERPETDOOR-SCHEDULE-CARD\s*%c\s*v(?P<version>\d+\.\d+\.\d+)")


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=False)


def extract_versions(source: str) -> tuple[str | None, str | None]:
    """(header version, banner version) - either may be None if absent."""
    header = _HEADER.search(source)
    banner = _BANNER.search(source)
    return (
        header.group("version") if header else None,
        banner.group("version") if banner else None,
    )


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def check_consistency(source: str) -> list[str]:
    """The card must agree with itself about what version it is."""
    header, banner = extract_versions(source)
    problems: list[str] = []
    if header is None:
        problems.append(f"{CARD}: no `Schedule Card vX.Y.Z` version in the file header")
    if banner is None:
        problems.append(f"{CARD}: no `POWERPETDOOR-SCHEDULE-CARD %c vX.Y.Z` console banner")
    if header and banner and header != banner:
        problems.append(
            f"{CARD}: header says v{header} but the console banner says v{banner}. "
            "A user reading the browser console and a user reading the source get "
            "different answers; pick one and set both."
        )
    return problems


def resolve_base(explicit: str | None) -> str | None:
    """What to diff against: an explicit ref, the upstream base, or HEAD."""
    if explicit:
        return explicit
    for candidate in ("@{upstream}", "origin/main", "HEAD"):
        if _git("rev-parse", "--verify", "--quiet", f"{candidate}^{{commit}}").returncode == 0:
            return candidate
    return None


def check_bumped(base: str) -> list[str]:
    """If the card changed since `base`, its version must have changed too."""
    changed = _git("diff", "--name-only", base, "--", str(CARD))
    if changed.returncode != 0:
        # Not a failure: a shallow clone or a fresh repo legitimately has no
        # base to compare against. Reported, never silently passed as clean.
        return [f"could not diff {CARD} against {base}; skipping the bump check"]
    if not changed.stdout.strip():
        return []

    previous = _git("show", f"{base}:{CARD}")
    if previous.returncode != 0:
        # The card is new in this change; nothing to bump from.
        return []

    old_header, _ = extract_versions(previous.stdout)
    new_header, _ = extract_versions((REPO / CARD).read_text(encoding="utf-8"))
    if old_header is None or new_header is None:
        return []
    if old_header == new_header:
        return [
            f"{CARD} changed but its version is still v{new_header}. Home Assistant "
            "caches /local/ aggressively, so users will keep running the old card "
            "with no way to notice. Bump the header and the console banner."
        ]
    if _version_key(new_header) < _version_key(old_header):
        return [f"{CARD}: version went backwards, v{old_header} -> v{new_header}"]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="git ref to compare against (default: upstream, else HEAD)")
    parser.add_argument(
        "--consistency-only",
        action="store_true",
        help="only check that the card agrees with itself; skip the bump check",
    )
    args = parser.parse_args()

    path = REPO / CARD
    if not path.exists():
        print(f"OK: {CARD} does not exist; nothing to check")
        return 0

    source = path.read_text(encoding="utf-8")
    problems = check_consistency(source)

    if not args.consistency_only:
        base = resolve_base(args.base)
        if base is None:
            print("note: no git base to compare against; skipping the bump check")
        else:
            problems.extend(check_bumped(base))

    if problems:
        for problem in problems:
            print(f"FAIL: {problem}")
        return 1

    header, _ = extract_versions(source)
    print(f"OK: {CARD} is at v{header} and agrees with itself")
    return 0


if __name__ == "__main__":
    sys.exit(main())
