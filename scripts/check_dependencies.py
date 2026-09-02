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


def _resolve_uv() -> str:
    """The uv that owns this project, not whichever one is first on PATH.

    Home Assistant depends on `uv`, so `.venv/bin/uv` exists and is HA's
    pinned version - 0.9.26 against a developer's 0.12.7 at the time of
    writing. This script runs as `uv run python scripts/...`, which puts
    the venv first on PATH, so a bare "uv" reached the OLD one: it answers
    `lock --upgrade --dry-run` with a bare "Lockfile changes detected"
    whatever the answer is, which this script read as unparseable output
    and reported as a phantom pending upgrade on every single run. Under
    `--strict` that is a push blocked forever with nothing to fix.

    `uv run` exports the invoking binary's path as `$UV` precisely so a
    subprocess can find its way back to it.
    """
    return os.environ.get("UV") or shutil.which("uv") or "uv"


#: Resolved once. `uvx` ships beside `uv`, so it is found the same way.
UV = _resolve_uv()
UVX = str(Path(UV).with_name("uvx")) if Path(UV).name == "uv" else "uvx"


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def check_lock_matches_manifest() -> bool:
    """`uv.lock` resolves what `pyproject.toml` currently declares."""
    result = run([UV, "lock", "--check"])
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
    result = run([UV, "lock", "--upgrade", "--dry-run"])
    moves = parse_upgrade_moves(f"{result.stdout}\n{result.stderr}")
    if not moves:
        print("  every dependency is at its newest resolvable version")
        return []

    print(f"  {len(moves)} dependenc{'y' if len(moves) == 1 else 'ies'} could move:")
    for move in moves:
        print(f"    {move}")
    if fix:
        print("  applying with `uv lock --upgrade`...")
        upgrade = run([UV, "lock", "--upgrade"])
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
    if not Path(UV).is_file() and shutil.which(UV) is None:
        print("  skipped: uv not on PATH")
        return None

    result = run([UV, "export", "--format", "requirements-txt", "--no-hashes", "--all-extras"])
    if result.returncode != 0:
        print(f"  skipped: could not export requirements ({result.stderr.strip()})")
        return None

    audit = subprocess.run(
        [UVX, "pip-audit", "--format", "json", "--requirement", "/dev/stdin"],
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


def default_branch_head(repo: str) -> str | None:
    """The sha at the tip of a repo's default branch, or None."""
    head = _github_json(f"https://api.github.com/repos/{repo}/commits?per_page=1")
    if isinstance(head, list) and head and isinstance(head[0], dict):
        return str(head[0]["sha"])
    return None


def _version_key(tag: str) -> tuple[int, ...]:
    """Sort key for a `v1.2.3`-ish tag; non-numeric parts sort as zero."""
    return tuple(int(part) if part.isdigit() else 0 for part in re.findall(r"\d+|\w+", tag))


def check_npm_packages() -> list[str]:
    """Dev dependencies of the Lovelace card's test toolchain that have moved.

    The second ecosystem in this repo, and the one `uv` cannot see.
    `.github/dependabot.yml` watches it, so leaving it out of the freshness
    gate means npm is the only route left by which a Dependabot PR can
    appear - which is the condition this whole check exists to remove.

    Nothing npm resolves ever reaches a user: the card in `www/` is plain
    browser JavaScript with no build step, and these are jest and eslint.
    That makes an upgrade cheap to take and cheap to revert, so there is no
    reason to run behind.
    """
    if not Path("package.json").is_file():
        print("  no package.json; skipped")
        return []
    if shutil.which("npm") is None:
        print("  skipped: npm not on PATH")
        return []

    # `npm outdated` exits 1 when anything is outdated, which is the normal
    # case rather than an error.
    result = run(["npm", "outdated", "--json"])
    try:
        report = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        print("  skipped: could not parse `npm outdated` output")
        return []

    behind = [
        f"{name} {entry.get('current')} -> {entry.get('latest')}"
        for name, entry in sorted(report.items())
        if entry.get("current") != entry.get("latest")
    ]
    if not behind:
        print("  every npm dev dependency is at its latest release")
        return []
    print(f"  {len(behind)} npm dev dependenc{'y' if len(behind) == 1 else 'ies'} behind:")
    for entry in behind:
        print(f"    {entry}")
    return behind


def check_ruff_hook_pin() -> list[str]:
    """The ruff pre-commit hook is the ruff the lock resolves.

    `.pre-commit-config.yaml` pins ruff-pre-commit by tag, and `uv.lock`
    pins the ruff CI runs. Nothing couples them, so a lock refresh moves
    one and leaves the other - and a hook that formats differently from
    `ruff format --check` turns every commit into a fight with the lint
    job.
    """
    config = Path(".pre-commit-config.yaml")
    lock = Path("uv.lock")
    if not config.is_file() or not lock.is_file():
        print("  no ruff hook or lockfile to compare")
        return []

    hook = re.search(
        r"repo:\s*https://github\.com/astral-sh/ruff-pre-commit\s*\n(?:\s*#.*\n)*\s*rev:\s*v?([\d.]+)",
        config.read_text(encoding="utf-8"),
    )
    locked = re.search(
        r'\[\[package\]\]\nname = "ruff"\nversion = "([^"]+)"', lock.read_text(encoding="utf-8")
    )
    if not hook or not locked:
        print("  could not read one of the two ruff pins")
        return []

    if hook.group(1) != locked.group(1):
        message = (
            f"ruff-pre-commit v{hook.group(1)} -> v{locked.group(1)} "
            "(.pre-commit-config.yaml, to match uv.lock)"
        )
        print(f"  MISMATCH: {message}")
        return [message]
    print(f"  ruff hook and lock agree on v{hook.group(1)}")
    return []


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
    unresolved: list[str] = []
    for repo, (sha, comment, paths) in sorted(by_repo.items()):
        if repo.split("/")[0] in NON_GITHUB_OWNERS:
            where = ", ".join(sorted(str(p) for p in paths))
            print(f"  {repo}: not on github.com - track by hand ({where})")
            continue
        latest = latest_release_sha(repo)
        if latest is None:
            # Not "current" - *unknown*. Said out loud, because an API rate
            # limit reading as an all-clear is the silent staleness this
            # script exists to prevent.
            #
            # It does not fail, even under `--strict`: Dependabot covers
            # the github-actions ecosystem natively (.github/dependabot.yml),
            # so a pin that goes stale here still gets a PR. Blocking a push
            # on a network round trip that has a working backstop trades a
            # real outage for a duplicate one.
            print(f"  {repo}: could not resolve a latest release or tag")
            unresolved.append(repo)
            continue
        tag, latest_sha = latest
        if latest_sha != sha:
            # Differing from the newest tag is not the same as being behind
            # it. `home-assistant/actions` last cut a release in 2020 and has
            # developed on master ever since, so the pin every consumer uses
            # is SIX YEARS ahead of "latest" - and reporting that as stale
            # under `--strict` would block every push with the only "fix"
            # being a regression. A pin sitting on the default branch head is
            # current by definition, whatever tags exist behind it.
            if sha == default_branch_head(repo):
                print(f"  {repo}: at branch head, ahead of the newest tag ({tag})")
                continue
            stale.append(f"{repo} {comment or sha[:8]} -> {tag} ({latest_sha})")
        elif tag.startswith("HEAD"):
            print(f"  {repo}: at branch head; upstream publishes no tags")

    if unresolved:
        print(
            f"  {len(unresolved)} pin(s) could not be checked "
            "- set GITHUB_TOKEN if this is the API rate limit"
        )
    if not stale:
        if not unresolved:
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
        # Comment lines first. The scan below pairs up quote characters, and
        # an English apostrophe is one: the prose explaining why `tzdata` is
        # absent spans "Home Assistant's" to "manifest.json's", so everything
        # between them was read as a requirement named `s` and reported as a
        # disagreement on every run. Only whole-line comments are dropped, so
        # a `#` inside a requirement string cannot be eaten with them.
        body = "\n".join(
            line for line in block.group(1).splitlines() if not line.lstrip().startswith("#")
        )
        for entry in re.findall(r"[\"']([^\"']+)[\"']", body):
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

    print("\nCard toolchain (npm):")
    stale_npm = check_npm_packages()

    print("\nRuff hook pin:")
    stale_hook = check_ruff_hook_pin()

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
    pending = len(moves) + len(stale_actions) + len(stale_hook) + len(stale_npm)
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
