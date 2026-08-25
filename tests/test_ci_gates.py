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
import re
import subprocess
from pathlib import Path

import pytest
import yaml
from homeassistant.components.schedule import CONF_FROM, CONF_TO, WEEKDAY_TO_CONF

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

        text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        block = re.search(r"^dependencies\s*=\s*\[(.*?)^\]", text, re.S | re.M)
        assert block, "pyproject.toml has no [project] dependencies block"
        declared = {
            _requirement_name(e) for e in re.findall(r"[\"']([^\"']+)[\"']", block.group(1))
        }

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


class TestTheBorrowedScheduleConstants:
    """`schedule.py` imports three names from Home Assistant's own component.

        from homeassistant.components.schedule import (
            CONF_FROM, CONF_TO, WEEKDAY_TO_CONF,
        )

    They live in that component's `const.py`, which carries no stability
    contract. If any of them is renamed, `schedule.py` raises ImportError at
    import - and both `binary_sensor.py` and `websocket.py` import it, so
    setup fails outright: no entities, no card, no schedules, for everyone.

    hassfest cannot see this. `find_non_referenced_integrations` skips any
    reference whose name matches a file in the integration, and
    `custom_components/powerpetdoor/schedule.py` matches `schedule` - so it
    reads the import as our own platform file and validates nothing about
    it, in either direction.

    Pinning the VALUES rather than just the names is what makes this useful:
    the payload shape is Home Assistant's schedule format, which is a
    contract with every automation calling `powerpetdoor.set_schedule` and
    with the card. A silent change to `"from"` or to the weekday spelling
    would rewrite that payload with the suite green.
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

    def test_the_manifest_declares_the_dependency_the_import_creates(self):
        """Importing another integration requires declaring it.

        Asserted because the declaration looks removable: nothing in this
        repo fails without it, hassfest does not check it, and it costs
        every user a `schedule` component they never asked for. It is still
        required - Home Assistant may not have loaded that component when
        `schedule.py` is imported.
        """
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        assert "schedule" in manifest.get("dependencies", []), (
            "schedule.py imports from homeassistant.components.schedule, "
            "so the manifest must declare it"
        )
