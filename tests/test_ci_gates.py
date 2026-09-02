# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""Invariants about the repository's own configuration.

None of these test behaviour. They exist because each one has a failure
mode that is invisible to every other test in the suite and that only shows
up in production, in CI, or in a user's Home Assistant log.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from unittest import mock

import pytest
import yaml
from homeassistant.components.schedule import CONF_FROM as HA_CONF_FROM
from homeassistant.components.schedule import CONF_TO as HA_CONF_TO
from homeassistant.components.schedule import WEEKDAY_TO_CONF as HA_WEEKDAY_TO_CONF

from custom_components.powerpetdoor.const import CONF_FROM, CONF_TO, WEEKDAY_TO_CONF

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPONENT = REPO_ROOT / "custom_components" / "powerpetdoor"
MANIFEST = COMPONENT / "manifest.json"


def _requirement_name(requirement: str) -> str:
    return re.split(r"[<>=!~\[; ]", requirement.strip(), maxsplit=1)[0].lower()


def _load_translation_checker():
    """Import scripts/check_translations.py, which is not a package."""
    spec = importlib.util.spec_from_file_location(
        "_check_translations", REPO_ROOT / "scripts" / "check_translations.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestBothRunnersGetTheSamePipeline:
    """The Gitea and GitHub workflows cannot drift apart.

    Gitea Actions reads only `.gitea/workflows/`, GitHub only
    `.github/workflows/`, so the pipeline exists twice. If they drift, one
    runner silently stops testing something.
    """

    def test_the_gitea_copy_matches_the_github_one(self):
        github = (REPO_ROOT / ".github/workflows/test.yml").read_text(encoding="utf-8")
        gitea = (REPO_ROOT / ".gitea/workflows/test.yml").read_text(encoding="utf-8")
        # The Gitea copy carries an explanatory header and is otherwise
        # byte-identical, so it must END WITH the GitHub file. Asserted as a
        # suffix rather than by stripping N comment lines: a stripping rule
        # silently passes if someone adds a comment mid-file.
        assert gitea.endswith(github), (
            ".gitea/workflows/test.yml has drifted from .github/workflows/test.yml"
        )


class TestShippedAndDevelopmentRequirementsAgree:
    """`manifest.json` is what users install; `pyproject.toml` is what CI tests.

    They are the same list expressed twice. When they drift, the suite
    passes against one version of the library while every user runs another
    - which is exactly how this repo reached a state where it could not
    import at all (manifest pinned pypowerpetdoor 0.3.0 while the code used
    a 0.4.0 symbol).
    """

    def test_the_two_lists_name_the_same_packages(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        shipped = {_requirement_name(r) for r in manifest["requirements"]}

        # Parsed as TOML, not scraped with a regex. The regex this replaced
        # matched every quoted run inside the block, comments included, so
        # an apostrophe in a comment ("Home Assistant\'s") registered as a
        # dependency named `s` and failed the build for a prose edit.
        pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        declared = {_requirement_name(e) for e in pyproject["project"]["dependencies"]}

        assert shipped == declared, (
            f"manifest.json requires {sorted(shipped)} but pyproject.toml "
            f"declares {sorted(declared)}"
        )

    def test_the_library_is_pinned_exactly_for_users(self):
        """Home Assistant installs the manifest list into a user's system.

        A floor (`>=`) there means two users on the same integration version
        can be running different library versions, which makes a bug report
        unreproducible.
        """
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        for requirement in manifest["requirements"]:
            assert "==" in requirement, f"{requirement!r} in manifest.json is not pinned exactly"


class TestTheMeasuredMatrixIsSelfConsistent:
    """`.github/ha-matrix.json` is generated; nothing may hand-edit it into
    a state the workflow cannot consume.
    """

    @staticmethod
    def _matrix() -> dict:
        return json.loads((REPO_ROOT / ".github/ha-matrix.json").read_text(encoding="utf-8"))

    def test_every_entry_has_what_the_workflow_reads(self):
        matrix = self._matrix()
        assert matrix["include"], "the matrix is empty; CI would test nothing"
        for entry in matrix["include"]:
            assert set(entry) >= {"python-version", "homeassistant", "phacc", "edge", "name"}

    def test_no_duplicate_jobs(self):
        """An interpreter with only one usable HA must not emit it twice."""
        seen = [
            (entry["python-version"], entry["homeassistant"]) for entry in self._matrix()["include"]
        ]
        assert len(seen) == len(set(seen)), f"duplicate matrix entries: {seen}"

    def test_the_declared_minimum_is_the_lowest_entry(self):
        # Compared on a numeric key, never as strings: "2024.10.0" sorts
        # BEFORE "2024.6.0" lexicographically, so a plain min() would have
        # declared the wrong minimum and been believed.
        def key(version: str) -> tuple[int, ...]:
            return tuple(int(part) for part in version.split(".") if part.isdigit())

        matrix = self._matrix()
        lowest = min((entry["homeassistant"] for entry in matrix["include"]), key=key)
        assert matrix["minimum_homeassistant"] == lowest


class TestTheCoverageGateCannotBeQuietlyDisabled:
    """The 100% gate is the whole point of the coverage job."""

    def test_pyproject_still_demands_one_hundred_percent(self):
        text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        assert re.search(r"^fail_under\s*=\s*100\b", text, re.M), (
            "pyproject.toml no longer sets fail_under = 100"
        )

    def test_the_workflow_enforces_it_and_is_not_neutered(self):
        workflow = yaml.safe_load(
            (REPO_ROOT / ".github/workflows/test.yml").read_text(encoding="utf-8")
        )
        job = workflow["jobs"]["coverage-report"]
        steps = [step for step in job["steps"] if "--fail-under=100" in str(step.get("run", ""))]
        assert steps, "no step in coverage-report enforces --fail-under=100"
        # A gate that is present but `continue-on-error` or `if: false` is
        # not a gate; both have happened in this family of repos.
        for step in steps:
            assert not step.get("continue-on-error"), "the coverage gate is continue-on-error"
            assert "if" not in step, "the coverage gate is conditional"


class TestTheQualityScaleFileIsHonest:
    """A `done` with no implementation is worse than a `todo`."""

    @staticmethod
    def _rules() -> dict:
        data = yaml.safe_load((COMPONENT / "quality_scale.yaml").read_text(encoding="utf-8"))
        return data["rules"]

    def test_every_exempt_rule_explains_itself(self):
        for name, value in self._rules().items():
            if isinstance(value, dict) and value.get("status") == "exempt":
                assert value.get("comment", "").strip(), f"{name} is exempt with no explanation"

    def test_the_manifest_claims_a_scale_the_file_describes(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        assert manifest["quality_scale"] == "platinum"
        rules = self._rules()
        # The three platinum-tier rules must all be resolved, or the claim
        # in manifest.json is not backed by anything.
        for rule in ("async-dependency", "inject-websession", "strict-typing"):
            value = rules[rule]
            status = value["status"] if isinstance(value, dict) else value
            assert status in ("done", "exempt"), f"platinum rule {rule} is {status}"


class TestEveryPlatformDeclaresParallelUpdates:
    """Platinum's `parallel-updates`. Missing it is invisible at runtime."""

    @pytest.mark.parametrize(
        "platform",
        ["binary_sensor", "button", "cover", "number", "select", "sensor", "switch"],
    )
    def test_platform_declares_it(self, platform: str):
        source = (COMPONENT / f"{platform}.py").read_text(encoding="utf-8")
        assert re.search(r"^PARALLEL_UPDATES\s*=\s*\d+", source, re.M), (
            f"{platform}.py does not declare PARALLEL_UPDATES"
        )


class TestNoEntityHardcodesItsName:
    """`has-entity-name` + `entity-translations`, enforced structurally.

    An `_attr_name` string is text the user sees in a language nobody asked
    them about, and it is the single easiest platinum rule to regress on.
    """

    def test_no_attr_name_anywhere(self):
        offenders = []
        for path in COMPONENT.rglob("*.py"):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if re.match(r"\s*_attr_name\s*=", line):
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}")
        assert not offenders, f"hardcoded entity names at: {', '.join(offenders)}"


class TestTheDeclaredMinimumIsTheMeasuredOne:
    """`hacs.json` tells users which Home Assistant they need.

    It is the only place a user sees the minimum before installing, and
    nothing else in the repo would notice it going stale. It must equal the
    lowest entry the matrix was actually measured against - a hand-typed
    number here is a promise CI never tested.
    """

    def test_hacs_json_matches_the_matrix(self):
        hacs = json.loads((REPO_ROOT / "hacs.json").read_text(encoding="utf-8"))
        matrix = json.loads((REPO_ROOT / ".github/ha-matrix.json").read_text(encoding="utf-8"))
        assert hacs["homeassistant"] == matrix["minimum_homeassistant"], (
            f"hacs.json promises HA {hacs['homeassistant']} but the matrix was "
            f"measured from {matrix['minimum_homeassistant']}"
        )


class TestTheReadmeVersionTableMatchesTheMatrix:
    """The README's supported-versions table is the first thing a user reads.

    It is also the easiest thing in the repo to forget: the matrix is
    regenerated by a script, and nothing would notice the hand-written table
    beside it going stale. pypowerpetdoor's README tree drifted for exactly
    this reason - it lost a whole subsystem and only a human reading it
    would have known.
    """

    def test_every_measured_pair_appears_in_the_readme(self):
        matrix = json.loads((REPO_ROOT / ".github/ha-matrix.json").read_text(encoding="utf-8"))
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

        table = re.search(
            r"\| Python \| Oldest Home Assistant \| Newest Home Assistant \|(.*?)\n\n",
            readme,
            re.S,
        )
        assert table, "README.md no longer has a supported-versions table"
        rows = table.group(1)

        by_python: dict[str, dict[str, str]] = {}
        for entry in matrix["include"]:
            by_python.setdefault(entry["python-version"], {})[entry["edge"]] = entry[
                "homeassistant"
            ]

        for python, edges in by_python.items():
            for version in edges.values():
                assert version in rows, (
                    f"README's table does not mention HA {version} (python {python}), "
                    "which the matrix was measured against"
                )
            assert python in rows, f"README's table does not mention Python {python}"

    def test_the_readme_states_the_measured_minimum(self):
        matrix = json.loads((REPO_ROOT / ".github/ha-matrix.json").read_text(encoding="utf-8"))
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        assert f"Minimum Home Assistant: {matrix['minimum_homeassistant']}" in readme, (
            "README.md does not state the measured minimum Home Assistant version"
        )


class TestActionsAreFullyDescribed:
    """`services.yaml` and `strings.json` describe the same actions.

    Home Assistant renders the action picker from `strings.json`, and the
    form from `services.yaml`. A field present in one and not the other
    shows the user a raw translation key where a label should be - visible
    only by opening the action in the UI, which no other test does.
    """

    @staticmethod
    def _services() -> dict:
        return yaml.safe_load((COMPONENT / "services.yaml").read_text(encoding="utf-8"))

    @staticmethod
    def _strings() -> dict:
        return json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))

    def test_every_action_has_a_name_and_description(self):
        described = self._strings().get("services", {})
        for name in self._services():
            assert name in described, f"{name} is in services.yaml but not strings.json"
            assert described[name].get("name"), f"{name} has no name"
            assert described[name].get("description"), f"{name} has no description"

    def test_no_described_action_has_been_removed(self):
        defined = set(self._services())
        for name in self._strings().get("services", {}):
            assert name in defined, f"{name} is described in strings.json but does not exist"

    def test_every_field_is_described(self):
        described = self._strings().get("services", {})
        for name, spec in self._services().items():
            fields = set(spec.get("fields", {}))
            documented = set(described.get(name, {}).get("fields", {}))
            assert fields == documented, (
                f"{name}: services.yaml has fields {sorted(fields)} but "
                f"strings.json describes {sorted(documented)}"
            )


class TestShippedPinsAreTheTestedPins:
    """`manifest.json` must pin the version CI actually tested.

    Name-only agreement is not enough, and this repo proved it: the manifest
    pinned `tzdata==2025.2` - which is what Home Assistant installs into a
    user's system - while the lockfile resolved 2026.3, which is what every
    test ran against. tzdata is not inert here: `tz_utils` reads IANA rules
    out of it to compute the POSIX string written to the door, so it decides
    when the door actually opens. A zone whose DST rules moved between those
    releases would send a stale rule to real hardware, and no test could see
    it. The existing guards compared package *names* only and reported
    "manifest.json and pyproject.toml agree" throughout.
    """

    @staticmethod
    def _locked_versions() -> dict[str, str]:
        """Every package version pinned by uv.lock."""
        text = (REPO_ROOT / "uv.lock").read_text(encoding="utf-8")
        versions: dict[str, str] = {}
        for block in text.split("[[package]]"):
            name = re.search(r'^name = "([^"]+)"', block, re.M)
            version = re.search(r'^version = "([^"]+)"', block, re.M)
            if name and version:
                versions[name.group(1).lower()] = version.group(1)
        return versions

    def test_manifest_pins_match_the_lockfile(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        locked = self._locked_versions()

        for requirement in manifest["requirements"]:
            name, _, pinned = requirement.partition("==")
            name = name.strip().lower()
            pinned = pinned.strip()
            assert name in locked, f"{name} is in manifest.json but not in uv.lock"
            assert pinned == locked[name], (
                f"manifest.json ships {name}=={pinned} to users, but uv.lock "
                f"resolves {locked[name]} - so the tested version is not the "
                "shipped version"
            )


class TestTheFrontendToolchainIsReproducible:
    """`npm ci` needs a committed lockfile, and fails opaquely without one.

    The Lint and Card Tests jobs both run `npm ci`, which - unlike
    `npm install` - refuses to run at all if `package-lock.json` is missing
    or out of step with `package.json`. The error it prints does not mention
    the lockfile, so a missing one costs a confusing CI failure rather than
    an obvious one.
    """

    def test_the_lockfile_exists(self):
        assert (REPO_ROOT / "package-lock.json").is_file(), (
            "package-lock.json is missing; `npm ci` in CI will fail"
        )

    def test_the_lockfile_is_not_ignored(self):
        """It is only useful if it is actually committed."""
        result = subprocess.run(
            ["git", "check-ignore", "package-lock.json"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0, "package-lock.json is gitignored, so CI would never see it"

    def test_it_describes_the_same_package(self):
        package = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))
        lock = json.loads((REPO_ROOT / "package-lock.json").read_text(encoding="utf-8"))
        assert lock["name"] == package["name"], (
            "package-lock.json belongs to a different package than package.json"
        )
        # Every devDependency package.json asks for must be resolved in the
        # lock, or `npm ci` errors out.
        resolved = set(lock.get("packages", {}))
        for dependency in package.get("devDependencies", {}):
            assert f"node_modules/{dependency}" in resolved, (
                f"{dependency} is in package.json but not resolved in package-lock.json"
            )


class TestTranslatedTextIsParseableByHomeAssistant:
    """Home Assistant parses `{...}` in every translated string.

    Whatever is inside must be an identifier; a literal brace is written
    `{{`. A string that breaks the rule is rejected by hassfest, which runs
    nightly - and which spent months failing on its own broken container
    image, so nothing was checking this at all. `{"monday": [...]}` shipped
    in a service description that way.

    `scripts/check_translations.py` did not catch it either: its regex
    matched only VALID placeholders, so it compared an empty set to an empty
    set and reported clean. This pins the check that closed that gap - the
    third green-checker-that-checks-nothing found in this repo, and the
    reason a checker needs a test of its own.
    """

    def test_no_shipped_string_contains_an_unparseable_brace(self):
        checker = _load_translation_checker()
        for path in (
            COMPONENT / "strings.json",
            *sorted((COMPONENT / "translations").glob("*.json")),
        ):
            flat = checker.flatten(json.loads(path.read_text(encoding="utf-8")))
            assert checker.bad_placeholders(flat) == [], path.name

    @pytest.mark.parametrize(
        ("text", "rejected"),
        [
            ("Door at {host}:{port} did not answer", False),
            ("Use {{ }} to escape a brace", False),
            ("No braces here at all", False),
            # The one that actually shipped.
            ('for example {"monday": [...]}', True),
            # A space is not an identifier character, and this is the shape a
            # well-meaning translator produces.
            ("the {day name} window", True),
            ("{}", True),
        ],
    )
    def test_each_shape_is_judged_on_its_own(self, text, rejected):
        checker = _load_translation_checker()
        assert bool(checker.bad_placeholders({"k": text})) is rejected


class TestTheUnitMatrixMatchesTheMeasuredGrid:
    """The workflow fans out over a STATIC copy of `.github/ha-matrix.json`.

    Reading the grid at run time would be the obvious way to keep the two
    honest, and it is what this workflow used to do. It cannot: Gitea breaks
    on a run-time matrix in two different ways. Spelled `matrix.include:`,
    the unevaluated expression reaches an unchecked type assertion in act's
    `Job.GetMatrixes()` during Gitea's static parse and panics the request -
    HTTP 500 on the repo settings page, and no Actions tab at all. Moved onto
    `matrix:` itself it parses, but the runner never expands it: one job
    runs, named the literal `${{ matrix.name }}`, logging `'runs-on' key not
    defined` and `No steps found`. Four measured pairs became one job that
    tested nothing, and every other job in the run was cancelled with it.

    So the grid is expanded at authoring time by
    `scripts/expand_ci_matrix.py`, which makes this the assertion that stops
    the copy going stale - a matrix that silently stopped covering a
    supported Python is exactly the failure the measurement exists to
    prevent.
    """

    def test_the_workflow_matrix_is_the_json_verbatim(self):
        matrix = json.loads((REPO_ROOT / ".github/ha-matrix.json").read_text(encoding="utf-8"))
        workflow = yaml.safe_load(
            (REPO_ROOT / ".github/workflows/test.yml").read_text(encoding="utf-8")
        )
        include = workflow["jobs"]["unit-tests"]["strategy"]["matrix"]["include"]

        # Compared on the fields the workflow actually carries, so adding a
        # purely informational key to the JSON does not fail the build.
        fields = ("name", "python-version", "homeassistant", "phacc", "edge")
        assert [{k: str(row[k]) for k in fields} for row in include] == [
            {k: str(row[k]) for k in fields} for row in matrix["include"]
        ], "run scripts/expand_ci_matrix.py"

    def test_the_matrix_is_not_an_unexpanded_expression(self):
        """The exact shape that produced one silent do-nothing job.

        `yaml.safe_load` turns both the broken spellings into a plain
        string, so this catches either without needing to know which.
        """
        for name in (".github/workflows/test.yml", ".gitea/workflows/test.yml"):
            workflow = yaml.safe_load((REPO_ROOT / name).read_text(encoding="utf-8"))
            strategy = workflow["jobs"]["unit-tests"]["strategy"]
            assert isinstance(strategy["matrix"], dict), f"{name}: matrix is an expression"
            assert isinstance(strategy["matrix"]["include"], list), f"{name}: include is not a list"


#: Home Assistant's own `script.hassfest.quality_scale.ALL_RULES`, by name.
#:
#: Pinned by literal because nothing in this repo can derive it. hassfest's
#: quality-scale plugin opens with `if not integration.core: return`, so the
#: CI hassfest run - which is what the `quality_scale: platinum` claim in
#: manifest.json rests on - never opens this file. Read out of the pinned
#: hassfest image with:
#:
#:     docker run --rm --entrypoint sh ghcr.io/home-assistant/hassfest -c \
#:       'cd /usr/src/homeassistant && python3 -c "
#:        from script.hassfest.quality_scale import ALL_RULES
#:        print(chr(10).join(sorted(r.name for r in ALL_RULES)))"'
#:
#: Re-run that when a new Home Assistant release lands; a rule added upstream
#: is a rule this integration silently stops being measured against.
HA_QUALITY_SCALE_RULES = frozenset(
    [
        "action-exceptions",
        "action-setup",
        "appropriate-polling",
        "async-dependency",
        "brands",
        "common-modules",
        "config-entry-unloading",
        "config-flow",
        "config-flow-test-coverage",
        "dependency-transparency",
        "devices",
        "diagnostics",
        "discovery",
        "discovery-update-info",
        "docs-actions",
        "docs-conditions",
        "docs-configuration-parameters",
        "docs-data-update",
        "docs-examples",
        "docs-high-level-description",
        "docs-installation-instructions",
        "docs-installation-parameters",
        "docs-known-limitations",
        "docs-removal-instructions",
        "docs-supported-devices",
        "docs-supported-functions",
        "docs-triggers",
        "docs-troubleshooting",
        "docs-use-cases",
        "dynamic-devices",
        "entity-category",
        "entity-device-class",
        "entity-disabled-by-default",
        "entity-event-setup",
        "entity-translations",
        "entity-unavailable",
        "entity-unique-id",
        "exception-translations",
        "has-entity-name",
        "icon-translations",
        "inject-websession",
        "integration-owner",
        "log-when-unavailable",
        "parallel-updates",
        "reauthentication-flow",
        "reconfiguration-flow",
        "repair-issues",
        "runtime-data",
        "stale-devices",
        "strict-typing",
        "test-before-configure",
        "test-before-setup",
        "test-coverage",
        "unique-config-entry",
    ]
)


class TestTheQualityScaleFileCoversEveryRule:
    """Every rule Home Assistant defines must appear, or the tier is a claim.

    `quality_scale.yaml`'s schema makes each rule key `vol.Required`, and the
    tier check refuses a tier whose rules are not all resolved. Three rules -
    `common-modules`, `docs-conditions`, `docs-triggers` - were simply absent,
    so the file failed validation and Bronze was not met, which means neither
    was Platinum, while `manifest.json` said `platinum` and CI stayed green.

    Nothing caught it and nothing could: hassfest's quality-scale plugin
    returns immediately for a non-core integration, so the file it is meant
    to validate is never read on a custom component. This is that check.
    """

    @staticmethod
    def _rules() -> set[str]:
        data = yaml.safe_load((COMPONENT / "quality_scale.yaml").read_text(encoding="utf-8"))
        return set(data["rules"])

    def test_no_rule_is_missing(self):
        missing = sorted(HA_QUALITY_SCALE_RULES - self._rules())
        assert not missing, f"quality_scale.yaml is missing: {missing}"

    def test_no_rule_is_invented(self):
        """A typo'd key is silently ignored by everything, including us."""
        extra = sorted(self._rules() - HA_QUALITY_SCALE_RULES)
        assert not extra, f"quality_scale.yaml has rules Home Assistant does not define: {extra}"

    def test_nothing_is_left_todo_while_the_manifest_claims_platinum(self):
        """The tier gate: a `todo` anywhere means the claimed tier is not met."""
        data = yaml.safe_load((COMPONENT / "quality_scale.yaml").read_text(encoding="utf-8"))
        todo = sorted(
            name
            for name, value in data["rules"].items()
            if (value if isinstance(value, str) else value["status"]) == "todo"
        )
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        assert manifest["quality_scale"] == "platinum"
        assert not todo, f"manifest claims platinum but these are todo: {todo}"


class TestTheClonedScheduleConstants:
    """`const.py` clones three names from Home Assistant's own `schedule`.

        CONF_FROM, CONF_TO, WEEKDAY_TO_CONF

    They used to be imported, which made `schedule` a manifest dependency:
    every user loaded a component they never configured so this integration
    could spell "from". The import also sat on that component's `const.py`,
    which carries no stability contract - a rename there was an ImportError
    at setup, and `binary_sensor.py` and `websocket.py` both import
    `schedule.py`, so that meant no entities, no card, no schedules, for
    everyone.

    Cloning removes the dependency and the ImportError, and replaces them
    with the risk this class exists to cover: the two copies drifting apart
    in silence. The values ARE the payload format - a contract with every
    automation calling `powerpetdoor.set_schedule`, with the WebSocket API
    and with the Lovelace card - so `"from"` quietly becoming `"start"` in
    Home Assistant is something to find out about here rather than from a
    user whose dashboard stopped working.

    hassfest would not have caught either shape of this.
    `find_non_referenced_integrations` skips any reference whose name
    matches a file in the integration, and
    `custom_components/powerpetdoor/schedule.py` matches `schedule` - so it
    read the old import as our own platform file and validated nothing
    about it, in either direction.
    """

    def test_the_values_are_what_the_payload_format_promises(self):
        assert CONF_FROM == "from"
        assert CONF_TO == "to"
        assert WEEKDAY_TO_CONF == {
            0: "monday",
            1: "tuesday",
            2: "wednesday",
            3: "thursday",
            4: "friday",
            5: "saturday",
            6: "sunday",
        }

    def test_the_clone_still_matches_home_assistants_own(self):
        """The drift check the clone costs us.

        A test may import whatever it likes - test dependencies are not
        runtime dependencies - so this comparison is free where the runtime
        import was not.
        """
        assert (CONF_FROM, CONF_TO) == (HA_CONF_FROM, HA_CONF_TO)
        assert WEEKDAY_TO_CONF == HA_WEEKDAY_TO_CONF

    def test_the_manifest_declares_no_integration_dependency(self):
        """Nothing here imports another integration, so nothing is declared.

        Asserted because the reverse mistake is easy and invisible: adding
        `from homeassistant.components.<x> import ...` without declaring
        `<x>` works on a developer's machine, where something else has
        already loaded that component, and raises at setup for a user where
        nothing has. That is the bug this integration just removed, and
        hassfest cannot report it - it is only run in custom mode here.
        """
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        assert "dependencies" not in manifest

        sources = "\n".join(path.read_text(encoding="utf-8") for path in COMPONENT.glob("*.py"))
        imported = set(
            re.findall(
                r"^\s*from homeassistant\.components(?:\.(\w+)| import (\w+))",
                sources,
                flags=re.MULTILINE,
            )
        )
        imported = {name for pair in imported for name in pair if name}

        # A platform's own base classes (`homeassistant.components.cover`
        # and friends) are what a platform file IS, not a dependency: Home
        # Assistant loads them by virtue of the platform existing.
        platforms = {path.stem for path in COMPONENT.glob("*.py")}
        # `websocket_api` is the one real import left. Core's own practice
        # is to leave it undeclared - 57 of the 66 core integrations that
        # import it do - because a config with a frontend has always loaded
        # it, and the nine that declare it are the ones that also run
        # without one (backup, network, usb).
        undeclared = sorted(imported - platforms - {"websocket_api"})
        assert not undeclared, f"imports {undeclared} but declares no dependencies"


class TestTheCoreShapedSuiteStaysSelfContained:
    """`tests/components/powerpetdoor/` is what a core PR would copy whole.

    That is the entire value of the layout, and both halves of it decay
    quietly. A new `tests/test_<platform>.py` at the root still runs, still
    counts for coverage and still looks right in a diff - it just would not
    travel. And a fixture reached sideways out of `tests/simulator/` or
    `tests/fuzz/` leaves a directory that passes here and collapses the
    moment it is copied anywhere else.

    The dependency runs one way on purpose: the extras import the door
    doubles from the core-shaped suite, never the reverse. See
    `docs/development.md` for what a core submission would still change.
    """

    CORE_SUITE = REPO_ROOT / "tests" / "components" / "powerpetdoor"

    def test_no_platform_test_was_left_at_the_tests_root(self):
        stray = sorted(
            path.name
            for path in (REPO_ROOT / "tests").glob("test_*.py")
            # This one is about the repository, not the integration, so it
            # is the single file that belongs at the root.
            if path.name != "test_ci_gates.py"
        )
        assert not stray, f"belongs in tests/components/powerpetdoor/: {stray}"

    def test_the_core_suite_reaches_into_no_sibling_suite(self):
        offenders = sorted(
            path.name
            for path in self.CORE_SUITE.glob("*.py")
            if re.search(
                r"^\s*(from|import)\s+tests\.",
                path.read_text(encoding="utf-8"),
                flags=re.MULTILINE,
            )
        )
        assert not offenders, f"imports from a suite core would not take: {offenders}"


class TestEveryActionHasAnIcon:
    """`icons.json` must carry an icon for every action in `services.yaml`.

    Home Assistant renders an action without one as a generic cog in the UI
    action picker, and hassfest reports it as an error - but only in core
    mode, which is not how this integration is validated in CI, so nothing
    here would have said so. `set_schedule` shipped without one for exactly
    that reason.
    """

    def test_no_action_is_missing_its_icon(self):
        services = yaml.safe_load((COMPONENT / "services.yaml").read_text(encoding="utf-8"))
        icons = json.loads((COMPONENT / "icons.json").read_text(encoding="utf-8"))
        missing = sorted(set(services) - set(icons.get("services", {})))
        assert not missing, f"icons.json has no icon for: {missing}"

    def test_no_icon_names_an_action_that_does_not_exist(self):
        """A renamed action leaves its icon behind, pointing at nothing."""
        services = yaml.safe_load((COMPONENT / "services.yaml").read_text(encoding="utf-8"))
        icons = json.loads((COMPONENT / "icons.json").read_text(encoding="utf-8"))
        orphaned = sorted(set(icons.get("services", {})) - set(services))
        assert not orphaned, f"icons.json has icons for actions that do not exist: {orphaned}"


class TestTheGapsReportCanActuallyBeCommitted:
    """`TESTING_GAPS.md` says it is auto-generated by CI. It has to be true.

    It was not. The workflow declares `permissions: contents: read`, which
    is right for every job except the one that commits the regenerated
    report, and that job had no override - so the push was rejected:

        remote: error: User permission denied for writing.

    Silently, because the commit step is `continue-on-error`. The run went
    green, the file kept claiming to be auto-generated, and it had not been
    regenerated since 2026-08-23. A stale coverage report is worse than no
    report: it is a number people trust.
    """

    @staticmethod
    def _workflow(name: str) -> dict:
        return yaml.safe_load((REPO_ROOT / name).read_text(encoding="utf-8"))

    def test_the_coverage_job_may_write(self):
        for name in (".github/workflows/test.yml", ".gitea/workflows/test.yml"):
            job = self._workflow(name)["jobs"]["coverage-report"]
            assert job.get("permissions", {}).get("contents") == "write", (
                f"{name}: coverage-report cannot push the regenerated "
                "TESTING_GAPS.md without contents: write"
            )

    def test_no_other_job_may_write(self):
        """The default stays read-only; only the one that needs it differs.

        Asserted because the tempting fix was to widen the workflow-level
        permission, which would hand write access to every job including
        the ones that run third-party actions against the checkout.
        """
        for name in (".github/workflows/test.yml", ".gitea/workflows/test.yml"):
            workflow = self._workflow(name)
            assert workflow["permissions"]["contents"] == "read"
            writers = {
                job_name
                for job_name, job in workflow["jobs"].items()
                if job.get("permissions", {}).get("contents") == "write"
            }
            assert writers == {"coverage-report"}, f"{name}: unexpected writers {writers}"


def _load_dependency_checker():
    """Import scripts/check_dependencies.py, which is not a package."""
    spec = importlib.util.spec_from_file_location(
        "_check_dependencies", REPO_ROOT / "scripts" / "check_dependencies.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestTheDependencyGateCannotPassVacuously:
    """`check_dependencies.py` is a gate; a gate that never fires is a lie.

    It runs at pre-push with `--strict`, so its job is to make a Dependabot
    PR impossible by failing before the push that would earn one. Every
    assertion here pins a way it was found answering "all clear" without
    having looked.
    """

    def test_the_hook_runs_it_strictly(self):
        """Without `--strict` an available upgrade is printed, not refused.

        Which is the whole condition Dependabot opens a PR for.
        """
        config = yaml.safe_load((REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
        hooks = [
            hook
            for repo in config["repos"]
            for hook in repo.get("hooks", [])
            if hook.get("id") == "dependency-freshness"
        ]
        assert len(hooks) == 1, "dependency-freshness is not configured exactly once"
        assert "--strict" in hooks[0]["entry"].split(), (
            "the dependency-freshness hook must pass --strict, or an available "
            "upgrade is reported and the push proceeds anyway"
        )
        assert hooks[0]["stages"] == ["pre-push"], (
            "this resolves against PyPI and queries GitHub; at commit stage it "
            "would make committing offline impossible"
        )

    def test_it_reaches_the_projects_own_uv(self):
        """`$UV`, not PATH.

        Home Assistant depends on `uv`, so `.venv/bin/uv` exists and is
        older than the developer's. The hook runs under `uv run`, which puts
        the venv first on PATH - so a bare "uv" reached HA's copy, whose
        `lock --upgrade --dry-run` says "Lockfile changes detected" whatever
        the answer is. That parsed as unrecognised output and was reported
        as a pending upgrade on every run: under --strict, a permanently
        blocked push with nothing to fix.
        """
        module = _load_dependency_checker()
        with mock.patch.dict(os.environ, {"UV": "/opt/outer/bin/uv"}):
            assert module._resolve_uv() == "/opt/outer/bin/uv"
        # ...and `uvx` is taken from beside it, never from PATH either.
        assert Path(module.UVX).parent == Path(module.UV).parent

        # Only when `uv run` did not export it does PATH get a say.
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(module.shutil, "which", return_value="/venv/bin/uv"),
        ):
            assert module._resolve_uv() == "/venv/bin/uv"

        # The parse itself: HA's uv wording must not read as "unrecognised".
        assert (
            module.parse_upgrade_moves("Resolved 218 packages\nNo lockfile changes detected\n")
            == []
        )
        assert module.parse_upgrade_moves("Update ruff v0.16.4 -> v0.16.5\n") == [
            "Update ruff v0.16.4 -> v0.16.5"
        ]

    def test_prose_in_the_dependencies_block_is_not_a_requirement(self):
        """An apostrophe is a quote character to a regex.

        The comment explaining why `tzdata` is absent runs from "Home
        Assistant's" to "manifest.json's", and everything between them was
        read as a requirement named `s`. The script reported a manifest
        disagreement, and exited 1, on every single run.
        """
        module = _load_dependency_checker()
        assert module.check_manifest_matches_pyproject() == []

    def test_a_pin_ahead_of_the_newest_tag_is_not_behind_it(self):
        """`home-assistant/actions` last cut a release in 2020.

        Every consumer pins its master head, which is six years ahead of
        `1.0.0`. Reporting that as stale under --strict would block every
        push, with the only available "fix" being a six-year regression.
        """
        hassfest = (REPO_ROOT / ".github/workflows/hassfest.yml").read_text(encoding="utf-8")
        assert "home-assistant/actions/hassfest@" in hassfest
        module = _load_dependency_checker()
        assert hasattr(module, "default_branch_head"), (
            "check_action_pins needs the default-branch head to tell "
            "'differs from the newest tag' apart from 'behind it'"
        )


class TestTheRuffHookIsTheRuffCiRuns:
    """A hook that formats differently from CI fights the lint job.

    `.pre-commit-config.yaml` pins ruff-pre-commit by tag and `uv.lock` pins
    the ruff `ruff format --check` runs. Nothing in either file couples
    them, so a lock refresh moves one and leaves the other - and the result
    is a commit that the hook reformats and CI then rejects, or vice versa.
    """

    def test_the_pinned_versions_agree(self):
        config = (REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
        hook = re.search(
            r"repo:\s*https://github\.com/astral-sh/ruff-pre-commit\s*\n"
            r"(?:\s*#.*\n)*\s*rev:\s*v?([\d.]+)",
            config,
        )
        assert hook, "could not find the ruff-pre-commit rev"

        lock = (REPO_ROOT / "uv.lock").read_text(encoding="utf-8")
        locked = re.search(r'\[\[package\]\]\nname = "ruff"\nversion = "([^"]+)"', lock)
        assert locked, "uv.lock does not resolve ruff"

        assert hook.group(1) == locked.group(1), (
            f"the ruff pre-commit hook is v{hook.group(1)} but uv.lock resolves "
            f"{locked.group(1)}; the hook and CI would format differently"
        )


def _load_matrix_script():
    """Import scripts/ha_matrix.py, which is not a package.

    Registered in `sys.modules` before it is executed, unlike the two
    loaders above: this module defines dataclasses, and with
    `from __future__ import annotations` in force the decorator resolves
    each field's annotation through `sys.modules[cls.__module__]`. An
    unregistered module makes that None and the import dies inside
    `dataclasses`.
    """
    spec = importlib.util.spec_from_file_location(
        "_ha_matrix", REPO_ROOT / "scripts" / "ha_matrix.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        del sys.modules[spec.name]
        raise
    return module


class TestTheMatrixGateComparesLikeForLike:
    """`--check --quick` must be able to pass, and to fail.

    The pre-push hook runs `ha_matrix.py --check --quick`. `--quick` skips
    running the suite, so it finds every pair that merely INSTALLS - a wider
    grid, a lower floor, and `_measured_with_tests: false` in the document it
    builds. That was compared byte-for-byte against a file measured WITH
    tests, so the two differed by construction: the hook reported a perfectly
    current matrix as stale on every run and could only ever be skipped.
    """

    @staticmethod
    def _rows(module, spans: dict[str, tuple[str, str]]):
        return [
            module.PythonRow(
                python=python,
                oldest=module.Release(phacc="0.0.0", ha=oldest, requires_python=""),
                newest=module.Release(phacc="0.0.0", ha=newest, requires_python=""),
            )
            for python, (oldest, newest) in spans.items()
        ]

    def _run_check(self, module, spans: dict[str, tuple[str, str]]) -> int:
        rows = self._rows(module, spans)
        with (
            mock.patch.object(module, "build_matrix", return_value=rows),
            mock.patch.object(module.shutil, "which", return_value="/usr/bin/uv"),
            mock.patch.object(module.sys, "argv", ["ha_matrix.py", "--check", "--quick"]),
        ):
            return module.main()

    def test_a_wider_quick_probe_is_not_staleness(self):
        """The committed pairs sit INSIDE the resolvable span, not on its edge.

        A tested floor is by definition at or above the floor that merely
        installs, so comparing committed pairs against the probe's edge
        LIST - rather than its range - marks every one of them missing.
        """
        module = _load_matrix_script()
        committed = json.loads((REPO_ROOT / ".github" / "ha-matrix.json").read_text())
        assert committed["_measured_with_tests"], (
            "this gate only applies when the committed matrix was measured with tests"
        )

        spans = {}
        for entry in committed["include"]:
            versions = spans.setdefault(entry["python-version"], [])
            versions.append(entry["homeassistant"])
        # A quick probe reaching strictly wider than every committed pair,
        # which is the real-world shape.
        wide = {
            python: ("2024.1.0", max(versions, key=module._version_key))
            for python, versions in spans.items()
        }
        assert self._run_check(module, wide) == 0

    def test_a_pair_that_no_longer_resolves_still_fails(self):
        """...and the gate has not simply been turned off.

        Dropping the byte comparison without putting anything in its place
        would make the hook pass unconditionally, which is worse than
        failing unconditionally: it reads as a check.
        """
        module = _load_matrix_script()
        committed = json.loads((REPO_ROOT / ".github" / "ha-matrix.json").read_text())
        pythons = {entry["python-version"] for entry in committed["include"]}
        # Upstream yanked everything the committed matrix names.
        narrow = {python: ("2099.1.0", "2099.9.9") for python in pythons}
        assert self._run_check(module, narrow) == 1
