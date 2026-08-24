#!/usr/bin/env python3
"""Report dependencies that have drifted behind, and known CVEs.

Three separate questions, deliberately not conflated:

1. Is `uv.lock` consistent with `pyproject.toml`? A mismatch means
   `uv sync --locked` would refuse, so this is always an error.
2. Would a fresh resolve pick anything newer? `uv sync` never upgrades what
   is already pinned, so without this the lock rots silently - and with it
   the DST database in `tzdata`, the library's only runtime dependency and
   the thing the whole `tz_utils`/schedule feature reads its rules from.
3. Does anything in the resolved set have a published advisory?

Only 1 and 3 fail by default. Staleness is reported but not fatal unless
`--strict`, because a transitive release landing on a Tuesday is not a
reason for every push that week to go red.

Usage:
    python scripts/check_dependencies.py [--strict] [--fix]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

#: Advisories with no fixed version yet, or that provably cannot apply to
#: this project. Each entry needs a reason; an empty dict is the goal.
#:
#: A Home Assistant integration is unusual here: almost everything in the
#: resolved set is pinned by *Home Assistant*, not by us. aiohttp,
#: cryptography, yarl and friends arrive at whatever version the HA
#: release we test against pins, and a user's install takes HA's version
#: regardless of anything in this repo. So an advisory against one of
#: those is real, but it is not ours to fix - the fix is HA shipping a
#: bumped pin, and the only action available to us is to move the
#: supported HA range forward. Advisories against `pypowerpetdoor` or
#: `tzdata` ARE ours; those two are the entire list we control.
IGNORED_VULNERABILITIES: dict[str, str] = {}

#: Packages this repo actually chooses. See manifest.json/pyproject.
OURS = {"pypowerpetdoor", "tzdata"}


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def check_lock_matches_manifest() -> bool:
    """`uv.lock` resolves what `pyproject.toml` currently declares."""
    result = run(["uv", "lock", "--check"])
    if result.returncode == 0:
        print("  lock is consistent with pyproject.toml")
        return True
    print("  lock is STALE relative to pyproject.toml - run `uv lock`")
    print(f"    {result.stderr.strip().splitlines()[-1] if result.stderr.strip() else ''}")
    return False


#: uv's explicit "nothing to do" line. Detection keys off *this* rather
#: than off the move verbs, so that a wording change in uv surfaces as a
#: false alarm rather than as a silent all-clear.
NOTHING_TO_DO = "No lockfile changes detected"

#: What uv 0.12 actually emits per moved package: `Update tzdata v2024.1 ->
#: v2026.3`. Captured from a real stale lock, because the plausible guess
#: ("Updating", "Added", "Removed") matches none of it and made this
#: function report every stale lock as current.
_MOVE = re.compile(r"^(Update|Add|Remove|Downgrade|Bump)\b")

_UNRECOGNISED = "uv reported changes in a format this script did not recognise"


def parse_upgrade_moves(text: str) -> list[str]:
    """Lines describing what a fresh resolve would move."""
    if NOTHING_TO_DO in text:
        return []
    moves = [line.strip() for line in text.splitlines() if _MOVE.match(line.strip())]
    return moves or [_UNRECOGNISED]


def check_upgrades_available(fix: bool) -> list[str]:
    """What a fresh resolve would move, without writing the lockfile."""
    result = run(["uv", "lock", "--upgrade", "--dry-run"])
    moves = parse_upgrade_moves(f"{result.stdout}\n{result.stderr}")
    if not moves:
        print("  every dependency is at its newest resolvable version")
        return []

    print(f"  {len(moves)} dependenc{'y' if len(moves) == 1 else 'ies'} could move:")
    for move in moves:
        print(f"    {move}")
    if fix:
        print("  applying with `uv lock --upgrade`...")
        upgrade = run(["uv", "lock", "--upgrade"])
        if upgrade.returncode != 0:
            print(f"    failed: {upgrade.stderr.strip()}")
        else:
            print("    done - now re-run the full suite before committing the lock")
    return moves


def check_vulnerabilities() -> list[dict] | None:
    """Published advisories against the resolved set, via pip-audit.

    Returns None when pip-audit could not be run at all, which is reported
    but not treated as a clean bill of health.
    """
    if shutil.which("uv") is None:
        print("  skipped: uv not on PATH")
        return None

    result = run(["uv", "export", "--format", "requirements-txt", "--no-hashes", "--all-extras"])
    if result.returncode != 0:
        print(f"  skipped: could not export requirements ({result.stderr.strip()})")
        return None

    audit = subprocess.run(
        ["uvx", "pip-audit", "--format", "json", "--requirement", "/dev/stdin"],
        input=result.stdout,
        capture_output=True,
        text=True,
        check=False,
    )
    if audit.returncode not in (0, 1):
        print(f"  skipped: pip-audit unavailable ({audit.stderr.strip().splitlines()[-1:]})")
        return None

    try:
        report = json.loads(audit.stdout)
    except json.JSONDecodeError:
        print("  skipped: could not parse pip-audit output")
        return None

    found: list[dict] = []
    for dep in report.get("dependencies", []):
        for vuln in dep.get("vulns", []):
            vuln_id = vuln.get("id", "?")
            if vuln_id in IGNORED_VULNERABILITIES:
                print(f"  ignoring {vuln_id}: {IGNORED_VULNERABILITIES[vuln_id]}")
                continue
            found.append({"name": dep.get("name"), "version": dep.get("version"), **vuln})

    if not found:
        print("  no known advisories against the resolved set")
        return found

    # Split by who can actually act. Everything Home Assistant pins is
    # reported for awareness but does not fail the build: a user's install
    # takes HA's pin no matter what this repo says, so the only lever we
    # have is the supported HA range - not a version bump here.
    ours = [v for v in found if (v.get("name") or "").lower() in OURS]
    theirs = [v for v in found if (v.get("name") or "").lower() not in OURS]

    for label, group in (("ours", ours), ("pinned by Home Assistant", theirs)):
        if not group:
            continue
        print(f"  {len(group)} advisor{'y' if len(group) == 1 else 'ies'} ({label}):")
        # Home Assistant pins ~500 packages; a bad week produces dozens of
        # advisories in them and a wall of text trains people to skip the
        # whole section. Ours are never truncated.
        limit = len(group) if label == "ours" else 10
        for vuln in group[:limit]:
            fix = ", ".join(vuln.get("fix_versions") or []) or "no fix released"
            print(f"    {vuln['name']} {vuln['version']}: {vuln['id']} (fixed in: {fix})")
        if len(group) > limit:
            packages = sorted({v["name"] for v in group[limit:]})
            print(f"    ... and {len(group) - limit} more in: {', '.join(packages)}")
    if theirs and not ours:
        print("  -> nothing actionable here; these move when the supported HA range moves")
    return ours


# ---------------------------------------------------------------------------
# CI action pins
#
# Dependabot covers these on GitHub, but this repository's GitHub side is a
# push-mirror of Gitea: a Dependabot PR there cannot be merged into the
# source of truth, and the next mirror push overwrites whatever it did. So
# the same question has to be answerable locally, and on the Gitea runner.
# ---------------------------------------------------------------------------

#: `uses: owner/repo@<40-hex sha>  # v4`
_USES = re.compile(
    r"uses:\s*(?P<repo>[\w.-]+/[\w.-]+)"
    r"(?P<path>(?:/[\w.-]+)*)"
    r"@(?P<ref>[0-9a-f]{40})"
    r"\s*(?:#\s*(?P<comment>\S+))?"
)

WORKFLOW_ROOTS = (".github/workflows", ".gitea/workflows", ".github/actions")

#: Hosts other than github.com that `uses:` can point at. Their pins cannot
#: be resolved through the GitHub API, so they are reported as unresolvable
#: rather than silently treated as current - the Gitea reusable workflow is
#: the one `uses:` in this repo that receives a secret.
NON_GITHUB_OWNERS = {"neuromancy"}


def iter_action_pins() -> list[tuple[Path, str, str, str | None]]:
    """(file, owner/repo, pinned sha, version comment) for every `uses:` pin."""
    pins = []
    for root in WORKFLOW_ROOTS:
        base = Path(root)
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.y*ml")):
            for match in _USES.finditer(path.read_text(encoding="utf-8")):
                pins.append((path, match["repo"], match["ref"], match["comment"]))
    return pins


def _github_json(url: str) -> object | None:
    """GET a public GitHub API endpoint, or None if it cannot be read."""
    request = Request(url, headers={"Accept": "application/vnd.github+json"})
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read())
    except (URLError, TimeoutError, ValueError, OSError):
        return None


def latest_release_sha(repo: str) -> tuple[str, str] | None:
    """(tag, commit sha) of a repo's newest release, or None.

    Falls back to the tag list, because plenty of actions - the Gitea
    artifact shims among them - publish tags without ever cutting a GitHub
    "release", and reporting those as unresolvable forever is the same
    silent staleness this script exists to prevent.
    """
    release = _github_json(f"https://api.github.com/repos/{repo}/releases/latest")
    tag = ""
    if isinstance(release, dict) and "tag_name" in release:
        tag = str(release["tag_name"])
    else:
        tags = _github_json(f"https://api.github.com/repos/{repo}/tags")
        if isinstance(tags, list):
            versioned = [
                str(entry["name"])
                for entry in tags
                if isinstance(entry, dict) and re.match(r"v?\d", str(entry.get("name", "")))
            ]
            if versioned:
                tag = max(versioned, key=_version_key)
    if not tag:
        # No releases and no tags at all - the Gitea artifact shims are like
        # this. The only meaningful staleness signal left is the default
        # branch's head. Flagged separately by the caller, because moving a
        # pin to an untagged head is a supply-chain decision, not a routine
        # version bump.
        head = _github_json(f"https://api.github.com/repos/{repo}/commits?per_page=1")
        if isinstance(head, list) and head and isinstance(head[0], dict):
            return "HEAD (untagged)", str(head[0]["sha"])
        return None
    ref = _github_json(f"https://api.github.com/repos/{repo}/commits/{tag}")
    if not isinstance(ref, dict) or "sha" not in ref:
        return None
    return tag, str(ref["sha"])


def _version_key(tag: str) -> tuple[int, ...]:
    """Sort key for a `v1.2.3`-ish tag; non-numeric parts sort as zero."""
    return tuple(int(part) if part.isdigit() else 0 for part in re.findall(r"\d+|\w+", tag))


def check_action_pins() -> list[str]:
    """Action pins that are behind their upstream's latest release."""
    pins = iter_action_pins()
    if not pins:
        print("  no pinned actions found")
        return []

    # One network round trip and one line of output per repo, not per pin:
    # the same action is used a dozen times across these workflows.
    by_repo: dict[str, tuple[str, str | None, set[Path]]] = {}
    for path, repo, sha, comment in pins:
        entry = by_repo.setdefault(repo, (sha, comment, set()))
        entry[2].add(path)

    stale: list[str] = []
    for repo, (sha, comment, paths) in sorted(by_repo.items()):
        if repo.split("/")[0] in NON_GITHUB_OWNERS:
            where = ", ".join(sorted(str(p) for p in paths))
            print(f"  {repo}: not on github.com - track by hand ({where})")
            continue
        latest = latest_release_sha(repo)
        if latest is None:
            print(f"  {repo}: could not resolve a latest release or tag")
            continue
        tag, latest_sha = latest
        if latest_sha != sha:
            stale.append(f"{repo} {comment or sha[:8]} -> {tag} ({latest_sha})")
        elif tag.startswith("HEAD"):
            print(f"  {repo}: at branch head; upstream publishes no tags")

    if not stale:
        print("  every action pin is at its upstream's latest release")
        return []
    print(f"  {len(stale)} action pin(s) behind:")
    for entry in sorted(set(stale)):
        print(f"    {entry}")
    return sorted(set(stale))


# ---------------------------------------------------------------------------
# manifest.json vs pyproject.toml
#
# Home Assistant installs what `manifest.json` lists, at runtime, into the
# user's environment. `pyproject.toml` is what the dev venv and CI resolve.
# They are the same list expressed twice, and when they drift the tests pass
# against one library while users run another - which is exactly how this
# repo ended up unable to import at all (manifest wanted pypowerpetdoor
# 0.3.0 while the code used a 0.4.0 symbol).
# ---------------------------------------------------------------------------

MANIFEST = Path("custom_components/powerpetdoor/manifest.json")


def _requirement_name(requirement: str) -> str:
    return re.split(r"[<>=!~\[; ]", requirement.strip(), maxsplit=1)[0].lower()


def check_manifest_matches_pyproject() -> list[str]:
    """The shipped requirement list and the dev one name the same packages."""
    if not MANIFEST.is_file():
        print("  no manifest.json; skipped")
        return []
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    shipped = {_requirement_name(r): r.strip() for r in manifest.get("requirements", [])}

    text = Path("pyproject.toml").read_text(encoding="utf-8")
    block = re.search(r"^dependencies\s*=\s*\[(.*?)^\]", text, re.S | re.M)
    declared = {}
    if block:
        for entry in re.findall(r"[\"']([^\"']+)[\"']", block.group(1)):
            declared[_requirement_name(entry)] = entry.strip()

    problems = []
    for name in sorted(set(shipped) - set(declared)):
        problems.append(f"{shipped[name]} is in manifest.json but not pyproject.toml")
    for name in sorted(set(declared) - set(shipped)):
        problems.append(f"{declared[name]} is in pyproject.toml but not manifest.json")

    if problems:
        for problem in problems:
            print(f"  {problem}")
    else:
        print(f"  manifest.json and pyproject.toml agree on {len(shipped)} requirement(s)")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="also fail when a newer version is merely available",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="run `uv lock --upgrade` when upgrades are available",
    )
    args = parser.parse_args()

    print("Shipped vs. development requirements:")
    manifest_problems = check_manifest_matches_pyproject()

    print("\nLockfile consistency:")
    consistent = check_lock_matches_manifest()

    print("\nAvailable upgrades:")
    moves = check_upgrades_available(args.fix)

    print("\nCI action pins:")
    stale_actions = check_action_pins()

    print("\nSecurity advisories:")
    vulns = check_vulnerabilities()

    print()
    if manifest_problems:
        print(f"FAIL: manifest.json and pyproject.toml disagree ({len(manifest_problems)})")
        return 1
    if not consistent:
        print("FAIL: uv.lock does not match pyproject.toml")
        return 1
    if vulns:
        print(f"FAIL: {len(vulns)} known advisor{'y' if len(vulns) == 1 else 'ies'}")
        return 1
    pending = len(moves) + len(stale_actions)
    if pending and args.strict:
        print(f"FAIL (--strict): {pending} dependency/action update(s) available")
        return 1
    if pending:
        print(f"OK, with {pending} update(s) available - run with --fix to apply the lock ones")
        return 0
    print("OK: dependencies are current and free of known advisories")
    return 0


if __name__ == "__main__":
    sys.exit(main())
