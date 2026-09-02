#!/usr/bin/env python3
"""Measure which (CPython, Home Assistant) pairs this integration can run on.

Every other project in this family declares a Python matrix and moves on.
That does not work for a Home Assistant integration, because the supported
grid is not something we get to declare - it is a fact about upstream, and
it is bounded at *both* ends for every interpreter:

* **Lower bound.** Home Assistant's ``Requires-Python`` is a floor. HA
  2026.3.0 raised it to 3.14.2, so no interpreter older than that can run a
  current HA at all.
* **Upper bound.** Less obvious, and the reason this script exists rather
  than a lookup table: an *old* HA pins *old* transitive dependencies, and
  those have no wheels for a *new* interpreter. HA 2024.3 does not install
  on 3.14 no matter what its ``Requires-Python`` says, because the
  aiohttp/cryptography/propcache versions it pins predate 3.14 entirely and
  fall back to building from source against headers that have since changed.

So each interpreter has an oldest *and* a newest HA that actually resolves,
installs, and passes the suite, and neither end is derivable from metadata.
This script probes for both.

The unit of work is a ``pytest-homeassistant-custom-component`` release,
not a Home Assistant release: phacc pins exactly one HA version, and it is
the only way to get HA's own test fixtures at that version. Probing phacc
therefore probes HA, and gets us a usable ``hass`` fixture at the same time.

Output is ``.github/ha-matrix.json``, which the workflows read to build
their matrix, and a Markdown table for the docs. Re-run it when a new HA
lands, a new CPython lands, or you start using an API older HA lacks - the
floor moves on its own and this tells you where to.

Usage:
    python scripts/ha_matrix.py                 # probe, print, change nothing
    python scripts/ha_matrix.py --write         # ...and update ha-matrix.json
    python scripts/ha_matrix.py --check         # fail if the committed file is stale
    python scripts/ha_matrix.py --quick         # resolve-only; skip running tests
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MATRIX_FILE = REPO / ".github" / "ha-matrix.json"

#: Interpreters worth probing at all. Anything below 3.11 predates every HA
#: that has a config-entry API we would recognise.
CANDIDATE_PYTHONS = ["3.11", "3.12", "3.13", "3.14"]

#: Below this, Home Assistant has no ``ConfigEntry.runtime_data`` (added in
#: HA 2024.6), which is a *bronze* quality-scale rule. Supporting an older
#: HA would mean giving up a rule we are explicitly targeting, so the probe
#: does not even look further back. Raise this when a newer API becomes
#: load-bearing; never lower it to buy reach.
PLATINUM_FLOOR = (2024, 6)

PHACC = "pytest-homeassistant-custom-component"

#: A resolve failure that means "this pair is impossible", as opposed to a
#: transient network problem. Anything not matching is retried once and then
#: reported as indeterminate rather than silently recorded as unsupported -
#: a flaky index must not quietly shrink the published matrix.
_IMPOSSIBLE = re.compile(
    r"no solution found|does not satisfy|cannot be used|no matching distribution"
    r"|requires python|has no wheels|failed to build",
    re.IGNORECASE,
)


@dataclass
class Release:
    """One phacc release and the Home Assistant version it pins."""

    phacc: str
    ha: str
    requires_python: str

    @property
    def ha_key(self) -> tuple[int, ...]:
        return _version_key(self.ha)


@dataclass
class PythonRow:
    """The measured span of Home Assistant for one interpreter."""

    python: str
    oldest: Release | None = None
    newest: Release | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def supported(self) -> bool:
        return self.oldest is not None and self.newest is not None


def _version_key(version: str) -> tuple[int, ...]:
    """Sort key for a dotted version; non-numeric segments sort as zero."""
    return tuple(int(part) if part.isdigit() else 0 for part in re.findall(r"\d+|[a-z]+", version))


def _pypi(url: str) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None


def fetch_releases() -> list[Release]:
    """Every phacc release, newest first, annotated with the HA it pins.

    phacc publishes hundreds of releases and each one needs its own API
    call to learn the pinned HA version, so this walks backwards from the
    newest and stops at PLATINUM_FLOOR rather than fetching all of them.
    """
    index = _pypi(f"https://pypi.org/pypi/{PHACC}/json")
    if index is None:
        sys.exit(f"could not reach PyPI for {PHACC}")

    versions = sorted(index["releases"], key=_version_key, reverse=True)
    releases: list[Release] = []
    for version in versions:
        detail = _pypi(f"https://pypi.org/pypi/{PHACC}/{version}/json")
        if detail is None:
            continue
        info = detail["info"]
        pinned = [
            requirement
            for requirement in (info.get("requires_dist") or [])
            if requirement.lower().startswith("homeassistant")
        ]
        if not pinned:
            continue
        match = re.search(r"==\s*([0-9][^\s;]*)", pinned[0])
        if not match:
            continue
        ha = match.group(1)
        # Prereleases pin a beta HA; never publish a matrix entry that
        # points a user at one.
        if re.search(r"[ab]|rc", ha):
            continue
        release = Release(phacc=version, ha=ha, requires_python=info.get("requires_python") or "")
        if release.ha_key[:2] < PLATINUM_FLOOR:
            break
        releases.append(release)
    return releases


def _uv(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["uv", *args], capture_output=True, text=True, check=False)


def probe(python: str, release: Release, *, run_tests: bool) -> tuple[bool, str]:
    """Can `python` install this phacc, and does the suite pass on it?

    Returns (ok, detail). A resolve/install failure whose message does not
    look like a genuine incompatibility is reported as indeterminate, so a
    flaky index cannot silently shrink the matrix.
    """
    with tempfile.TemporaryDirectory(prefix="ha-matrix-") as tmp:
        venv = Path(tmp) / "venv"
        created = _uv("venv", "--python", python, str(venv))
        if created.returncode != 0:
            return False, f"no CPython {python} available"

        installed = _uv(
            "pip",
            "install",
            "--python",
            str(venv / "bin" / "python"),
            f"{PHACC}=={release.phacc}",
        )
        if installed.returncode != 0:
            message = f"{installed.stdout}\n{installed.stderr}"
            if _IMPOSSIBLE.search(message):
                return False, "incompatible"
            return False, "indeterminate (install failed, reason unclear)"

        if not run_tests:
            return True, "resolves"

        # Installing phacc gets HA and its fixtures; the integration's own
        # runtime deps still have to come from our manifest.
        deps = _uv(
            "pip",
            "install",
            "--python",
            str(venv / "bin" / "python"),
            *_runtime_requirements(),
            "pytest-xdist",
            "syrupy",
        )
        if deps.returncode != 0:
            return False, "indeterminate (runtime deps failed)"

        tests = subprocess.run(
            [
                str(venv / "bin" / "python"),
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                "--no-header",
                "-x",
                "--timeout=120",
                "-o",
                "addopts=",
                "--ignore=tests/fuzz",
            ],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
        )
        if tests.returncode != 0:
            tail = tests.stdout.strip().splitlines()[-1:] or [""]
            return False, f"tests fail ({tail[0][:80]})"
        return True, "tests pass"


def _runtime_requirements() -> list[str]:
    """manifest.json's requirements - what HA installs for us at runtime."""
    manifest = json.loads(
        (REPO / "custom_components" / "powerpetdoor" / "manifest.json").read_text(encoding="utf-8")
    )
    return list(manifest.get("requirements", []))


def _find_edge(
    python: str, releases: list[Release], *, run_tests: bool, oldest: bool
) -> Release | None:
    """Walk in from one end until a release works.

    A linear walk, not a bisect: support is *not* guaranteed contiguous (a
    single bad HA release in the middle of the range is entirely possible),
    and bisection on a non-monotonic predicate silently reports the wrong
    edge. The candidate list is short enough that walking is affordable and
    honest.
    """
    ordered = sorted(releases, key=lambda r: r.ha_key, reverse=not oldest)
    for release in ordered:
        ok, detail = probe(python, release, run_tests=run_tests)
        label = "oldest" if oldest else "newest"
        print(f"    {label:6} candidate HA {release.ha:<10} (phacc {release.phacc}): {detail}")
        if ok:
            return release
    return None


def build_matrix(pythons: list[str], *, run_tests: bool) -> list[PythonRow]:
    releases = fetch_releases()
    if not releases:
        sys.exit("no usable phacc releases found")
    print(
        f"Considering {len(releases)} phacc releases pinning HA "
        f"{releases[-1].ha} .. {releases[0].ha}\n"
    )

    rows: list[PythonRow] = []
    for python in pythons:
        print(f"CPython {python}:")
        row = PythonRow(python=python)
        row.newest = _find_edge(python, releases, run_tests=run_tests, oldest=False)
        if row.newest is None:
            row.notes.append("no Home Assistant in the supported range installs")
            print("    -> unsupported\n")
            rows.append(row)
            continue
        row.oldest = _find_edge(python, releases, run_tests=run_tests, oldest=True)
        if row.oldest is not None and row.oldest.ha == row.newest.ha:
            row.notes.append("only one Home Assistant release in range")
        print(f"    -> HA {row.oldest.ha if row.oldest else '?'} .. {row.newest.ha}\n")
        rows.append(row)
    return rows


def as_document(rows: list[PythonRow], *, tested: bool) -> dict:
    """The JSON the workflows consume."""
    include: list[dict[str, str]] = []
    for row in rows:
        if not row.supported:
            continue
        assert row.oldest is not None and row.newest is not None
        edges = [("min", row.oldest)]
        # Guard against emitting the same job twice when an interpreter has
        # exactly one usable HA.
        if row.newest.ha != row.oldest.ha:
            edges.append(("max", row.newest))
        for label, release in edges:
            include.append(
                {
                    "python-version": row.python,
                    "homeassistant": release.ha,
                    "phacc": release.phacc,
                    "edge": label,
                    "name": f"py{row.python} / HA {release.ha} ({label})",
                }
            )

    supported = [row for row in rows if row.supported]
    return {
        "_comment": (
            "Generated by scripts/ha_matrix.py - do not hand-edit. Each entry is a "
            "measured (CPython, Home Assistant) pair: 'min'/'max' are the oldest and "
            "newest HA that install and pass on that interpreter."
        ),
        "_measured_with_tests": tested,
        "minimum_homeassistant": (
            min((row.oldest.ha for row in supported if row.oldest), key=_version_key, default="")
        ),
        "maximum_homeassistant": (
            max((row.newest.ha for row in supported if row.newest), key=_version_key, default="")
        ),
        "pythons": [row.python for row in supported],
        "unsupported": {row.python: "; ".join(row.notes) for row in rows if not row.supported},
        "include": include,
    }


def as_markdown(document: dict) -> str:
    lines = [
        "| Python | Oldest Home Assistant | Newest Home Assistant |",
        "|--------|----------------------|-----------------------|",
    ]
    by_python: dict[str, dict[str, str]] = {}
    for entry in document["include"]:
        by_python.setdefault(entry["python-version"], {})[entry["edge"]] = entry["homeassistant"]
    for python, edges in sorted(by_python.items(), key=lambda item: _version_key(item[0])):
        lines.append(
            f"| {python} | {edges.get('min', '-')} | {edges.get('max', edges.get('min', '-'))} |"
        )
    for python, reason in sorted(document.get("unsupported", {}).items()):
        lines.append(f"| {python} | _unsupported_ | {reason} |")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="update .github/ha-matrix.json")
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if the committed matrix differs from a fresh probe",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="only check that each pair resolves; do not run the test suite",
    )
    parser.add_argument(
        "--python",
        action="append",
        dest="pythons",
        help="probe only this interpreter (repeatable)",
    )
    args = parser.parse_args()

    if shutil.which("uv") is None:
        sys.exit("uv is required: https://docs.astral.sh/uv/")

    rows = build_matrix(args.pythons or CANDIDATE_PYTHONS, run_tests=not args.quick)
    document = as_document(rows, tested=not args.quick)

    print(as_markdown(document))
    print()
    print(f"minimum Home Assistant: {document['minimum_homeassistant'] or 'none'}")
    print(f"maximum Home Assistant: {document['maximum_homeassistant'] or 'none'}")

    serialised = json.dumps(document, indent=2) + "\n"

    if args.check:
        if not MATRIX_FILE.exists():
            print(f"\nFAIL: {MATRIX_FILE.relative_to(REPO)} does not exist")
            return 1
        committed = json.loads(MATRIX_FILE.read_text(encoding="utf-8"))

        # A resolve-only probe cannot be compared byte-for-byte against a
        # file measured by running the suite, and this used to try. `--quick`
        # skips the tests, so it finds every pair that merely INSTALLS -
        # a wider grid, with a lower floor, and `_measured_with_tests: false`
        # in the document it builds. Against a committed file measured with
        # tests those differ by construction, so `--check --quick` reported
        # "stale" on a matrix that was perfectly current, every time, and the
        # pre-push hook that runs it could never pass.
        #
        # Like-for-like or not at all. A quick probe can still say something
        # true and useful: every committed pair must still resolve, which is
        # what catches an upstream yank. It cannot say the grid has not
        # moved, because it did not measure the same thing.
        if committed.get("_measured_with_tests") and not document["_measured_with_tests"]:
            # `include` carries only the EDGES of each interpreter's range,
            # so a committed pair is checked against the RANGE rather than
            # against that list - a tested floor sits inside the resolvable
            # span, not on its edge, and testing for membership marked every
            # one of them missing.
            probed: dict[str, list[str]] = {}
            for entry in document["include"]:
                probed.setdefault(entry["python-version"], []).append(entry["homeassistant"])
            missing = [
                entry
                for entry in committed["include"]
                if entry["python-version"] not in probed
                or not (
                    _version_key(min(probed[entry["python-version"]], key=_version_key))
                    <= _version_key(entry["homeassistant"])
                    <= _version_key(max(probed[entry["python-version"]], key=_version_key))
                )
            ]
            if missing:
                print(
                    f"\nFAIL: {MATRIX_FILE.relative_to(REPO)} claims pairs that no longer resolve:"
                )
                for entry in missing:
                    print(f"  {entry['name']}")
                print("  re-run with --write (without --quick) to re-measure")
                return 1
            print(
                f"\nOK: every committed pair in {MATRIX_FILE.relative_to(REPO)} still resolves"
                "\n    (quick mode: run without --quick to re-measure the grid itself)"
            )
            return 0

        if MATRIX_FILE.read_text(encoding="utf-8") != serialised:
            print(f"\nFAIL: {MATRIX_FILE.relative_to(REPO)} is stale - re-run with --write")
            return 1
        print(f"\nOK: {MATRIX_FILE.relative_to(REPO)} is current")
        return 0

    if args.write:
        MATRIX_FILE.parent.mkdir(parents=True, exist_ok=True)
        MATRIX_FILE.write_text(serialised, encoding="utf-8")
        print(f"\nwrote {MATRIX_FILE.relative_to(REPO)}")
        if not document["include"]:
            print("WARNING: the matrix is empty; refusing to treat that as success")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
