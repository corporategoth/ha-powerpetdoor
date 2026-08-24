# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ha-powerpetdoor is a **Home Assistant custom integration** for Power Pet Door
WiFi-enabled pet doors (High Tech Pet). It is distributed through HACS.

It has two halves:

- **`custom_components/powerpetdoor/`** — the integration. Entity platforms
  (cover, switch, sensor, binary_sensor, number, select, button), the config
  flow, a coordinator, and a WebSocket API for schedule editing.
- **`www/powerpetdoor-schedule-card.js`** — a custom Lovelace card for viewing
  and editing the door's schedules. Plain browser JavaScript, a native custom
  element. **Not Node** — no bundler, no imports, no `require`. It runs in the
  browser exactly as checked in.

All protocol work lives in the **`pypowerpetdoor`** library, not here.

### The library boundary (critical)

This integration talks to the door through `powerpetdoor.PowerPetDoor` — the
high-level door facade (cached state, properties, async control methods,
callbacks). It does **not** use `PowerPetDoorClient` directly, and it does not
speak the wire protocol.

If something needs a new command, a new field, or protocol-level behaviour, the
fix belongs in `pypowerpetdoor` (`~/src/pypowerpetdoor`), not here. Adding a
`send_message` call to this repo is a design failure, not a shortcut.

Related repos: `pypowerpetdoor` (the library and its door simulator),
`git.neuromancy.net/pypi/ostinato-powerpetdoor` (Ostinato plugin).

## Gitea is the source of truth. NEVER write to GitHub. (MANDATORY)

`origin` is **Gitea** (`git.neuromancy.net`). GitHub is a **push mirror**,
and a mirror is downstream: anything created there is either overwritten by
the next sync or stranded forever.

**Never, on GitHub:** create or edit a release, push, merge a pull request,
commit, edit the wiki, or move a tag. Not with `gh`, not through the web UI,
not through the API.

**Reading GitHub is fine and often necessary** - that is where users file
issues and pull requests, and `gh issue view` / `gh pr view` are the right
tools for it. The prohibition is on *writing*.

### Why - this has already gone wrong

A push mirror carries git refs only: "branches, tags, and commits", per
Gitea's own docs. A **release is a database object on each forge, not git
data**, so it can never cross that way.

pypowerpetdoor v0.4.1 was released by creating the release **on GitHub**.
The tag existed on both sides, so it looked fine - but Gitea had no release
object, the release-sync webhook had nothing to fire on, and the two forges
disagreed until it was recreated by hand. v0.4.0, cut correctly on Gitea,
appears on both at the same timestamp. That is the difference.

There is a second, sharper reason for pypowerpetdoor specifically:
`.github/workflows/release.yml` triggers on `release: published`. What
publishes to PyPI is therefore the **GitHub release object**. Cutting a
release on Gitea drives that chain correctly through the webhook; cutting it
on GitHub skips Gitea entirely and leaves the source of truth behind.

### How to cut a release

1. Tag and push to Gitea.
2. Create the release **in Gitea** - its UI, its API, or
   `tea releases create --repo <owner>/<repo> --tag vX.Y.Z --title ... --note ...`.
3. Let the webhook carry it to GitHub. Do not create it there yourself.

## Component Reuse (Critical)

**Before writing any code, check for existing implementations.**

1. **Library first**: anything about the door itself — state, commands,
   schedules, timezones, validation — is almost certainly already in
   `pypowerpetdoor`. Search it before writing a helper here.
2. **Home Assistant second**: HA ships helpers for nearly everything
   (`DataUpdateCoordinator`, `CoordinatorEntity`, `EntityDescription`,
   `device_registry`, config-flow helpers). Do not reimplement them.
3. **Two implementations = refactor**: if two entity platforms grow the same
   logic, it belongs in `entity.py` or `coordinator.py`.
4. **Extend, don't duplicate**: if an existing helper almost fits, extend it
   with parameters rather than creating a near-copy.

## Development Commands

```bash
# One-time setup: venv, dev deps, git hooks, npm deps for the card
./scripts/setup-dev.sh

# Python tests (pytest-xdist parallel by default via addopts)
uv run pytest

# A single test file
uv run pytest tests/test_switch.py

# With the 100% coverage gate
uv run pytest --cov

# Lint / format / types
uv run ruff check custom_components tests scripts
uv run ruff format --check custom_components tests scripts
uv run mypy custom_components

# Translations: strings.json vs translations/*.json, plus unwrapped text
uv run python scripts/check_translations.py --untranslated

# Frontend (Lovelace card) tests
npm test
npm run lint

# Which (python, HA) pairs actually work — regenerates the CI matrix
uv run python scripts/ha_matrix.py --write
```

## Home Assistant Version Matrix (MANDATORY)

**The supported matrix is measured, not declared.** Home Assistant's
`Requires-Python` is only a *floor*; an old HA also pins old transitive
dependencies that have no wheels for a *new* interpreter. So each Python has
both an oldest and a newest HA that actually installs and passes.

`scripts/ha_matrix.py` probes that grid and writes the result to
`.github/ha-matrix.json`, which the workflows read. Re-run it when:

- a new Home Assistant release lands,
- a new CPython release lands,
- you start using an API that older HA lacks (the floor will move up on its
  own, and the script will tell you where to).

### Rules

1. **Platinum beats reach.** If supporting an older HA would forfeit a
   quality-scale rule, drop the older HA. Known floors: `runtime_data`
   (HA 2024.6), `_get_reconfigure_entry` (2024.11), `quality_scale.yaml`
   (~2025.1).
2. **Never widen support by contorting the code.** No `hasattr` probes, no
   version sniffing, no compatibility shims to reach an older HA.
3. **The declared minimum lives in three places** and they must agree:
   `hacs.json` (`homeassistant`), `.github/ha-matrix.json`, and the README's
   requirements section. `tests/test_ci_gates.py` asserts this.

### Files that must stay in sync

| File | What to update |
|------|---------------|
| `.github/ha-matrix.json` | The measured (python, HA) grid; generated |
| `.github/workflows/test.yml` | Reads the matrix; `REFERENCE_PYTHON`, `REFERENCE_NODE` |
| `.gitea/workflows/test.yml` | Byte-identical to the above below its header |
| `pyproject.toml` | `requires-python`, classifiers, ruff `target-version`, mypy `python_version`, the two pinned `pytest-homeassistant-custom-component` versions |
| `hacs.json` | `homeassistant` minimum |
| `manifest.json` | `requirements`, `version`, `quality_scale` |

`manifest.json`'s `requirements` and `pyproject.toml`'s `dependencies` are the
same list expressed twice — Home Assistant installs the former at runtime, the
latter is what the dev venv and CI resolve. `tests/test_ci_gates.py` asserts
they agree.

### Manually tracked pins (MANDATORY)

`.github/dependabot.yml` covers `github-actions`, `uv`, and `npm`. Two things
sit outside anything automation can reach:

| Pin | Where | Why automation cannot see it |
|-----|-------|------------------------------|
| `neuromancy/workflows/.gitea/workflows/sync-github-wiki.yml@<sha>` | `.gitea/workflows/sync-wiki.yml` | Dependabot has no Gitea support. This is also the **only** `uses:` in the repo that receives a secret, so its SHA pin matters more than the rest |
| Transitive versions in `uv.lock` | `uv.lock` | `uv sync` never upgrades what is already pinned. Run `uv lock --upgrade` periodically and re-run the full suite |

## Quality Scale: Platinum (MANDATORY)

`custom_components/powerpetdoor/quality_scale.yaml` tracks every rule. A rule
is `done`, or `exempt` **with a comment explaining why**. Never mark a rule
`done` speculatively.

The rules this integration most easily regresses on:

- **`runtime-data`** — config entry state goes in `entry.runtime_data`, typed
  via a `ConfigEntry` alias. Never `hass.data[DOMAIN][...]`.
- **`has-entity-name`** — every entity sets `_attr_has_entity_name = True` and
  a `_attr_translation_key`. **No hardcoded `_attr_name`.**
- **`entity-translations` / `exception-translations`** — user-visible text
  comes from `strings.json`. Exceptions raise
  `HomeAssistantError(translation_domain=DOMAIN, translation_key=...)`.
- **`icon-translations`** — state-dependent icons go in `icons.json`, not an
  `icon` property. The battery icon ladder is the obvious trap.
- **`parallel-updates`** — every platform module declares `PARALLEL_UPDATES`.
- **`strict-typing`** — `mypy` runs with `disallow_untyped_defs`. The library
  ships `py.typed`, so its types are real; do not paper over them with `Any`.
- **`test-before-setup`** — raise `ConfigEntryNotReady` from
  `async_setup_entry` when the door is unreachable.

### Things that would fail HA review — do not reintroduce

- **Monkeypatching another integration.** The old code injected
  `async_setup_entry` into `homeassistant.components.schedule`. Verified
  against HA 2026.8.3: that component still has no `async_setup_entry`, so
  `async_forward_entry_setups(entry, "schedule")` cannot work without patching
  core. Schedules are our own entities plus the `powerpetdoor/schedule/*`
  WebSocket API and the Lovelace card.
- **YAML platform setup.** Config entries only.
- **Blocking I/O in the event loop.** Timezone cache building goes through
  `hass.async_add_executor_job`.
- **Bare `except:`** — the old `config_flow.py` had several. They swallow
  `KeyboardInterrupt` and `asyncio.CancelledError`.

## Testing Requirements (MANDATORY)

**Every code change MUST include corresponding tests.** This is non-negotiable.

Use Home Assistant's own test infrastructure
(`pytest-homeassistant-custom-component`): `hass` fixture,
`MockConfigEntry`, `async_fire_time_changed`, entity/device registry
fixtures, snapshot tests via `syrupy`. Do not hand-roll what it provides.

### Rules for Code Changes

1. **New Features**: unit tests covering the happy path, edge cases, error
   cases, and at least one negative test per public function.
2. **Bug Fixes**: a test that reproduces the bug (fails without the fix), the
   fix, and a regression test.
3. **Refactoring**: no reduction in coverage; add tests for new code paths.
4. **Frontend changes**: the card is tested under jsdom in `tests/frontend/`.
   A change to `www/powerpetdoor-schedule-card.js` needs a test there.

### Test Locations

| Code Location | Test Location |
|---------------|---------------|
| `custom_components/powerpetdoor/<platform>.py` | `tests/test_<platform>.py` |
| `custom_components/powerpetdoor/config_flow.py` | `tests/test_config_flow.py` |
| `custom_components/powerpetdoor/coordinator.py` | `tests/test_coordinator.py` |
| protocol-level round trips | `tests/simulator/` (drives the real simulator) |
| randomized input | `tests/fuzz/` (hypothesis) |
| `www/powerpetdoor-schedule-card.js` | `tests/frontend/unit/` |

### Coverage Requirements

- **100% line coverage** and **100% branch coverage**.
- `# pragma: no cover` requires justification and approval.
- The deterministic suite must reach the gate **without** `tests/fuzz/` — that
  is what CI's unit matrix runs.

### Test Quality Rules (Critical)

**Every test must have a single, deterministic expected outcome.**

1. **Tests must be specific**: assert exactly ONE expected result. If you write
   `assert x in (a, b)` for contradictory outcomes, the test is wrong.
2. **Never accept contradictory outcomes**: a test that accepts success AND
   failure means you do not know what the code does. Read it, then assert.
3. **Know the answer before running the test.** If you do not know what value
   to expect, read the production code and `pypowerpetdoor`'s `docs/protocol.md`
   until you do.
4. **Fix tests properly, never hunt for results.** When a test fails,
   investigate WHY. Do not change the expected value to match what happened.
5. **Never remove tests to "fix" failures.** The only valid reason to remove a
   test is complete redundancy. Difficulty is NEVER a valid reason.
6. **No fake tests**: no `assert True`, no tautologies, no test that merely
   reads back a value it just set.
7. **Async determinism**: never sleep-and-hope. Use `async_fire_time_changed`,
   `asyncio.Event`, or awaited futures.
8. **Assert at a boundary that decides something**: where a limit gates real
   behaviour (schedule window start/end, the low-battery crossing, hold-time
   min/max), assert on both sides of it. Coverage cannot see this class.
9. **Make the second operand of a compound condition decisive**: `if A and B:`
   is one branch point with two destinations, so 100% branch coverage is
   reached without ever running `A and not B`.
10. **Pin user-visible strings by literal.** Entity translation keys and
    `strings.json` keys are a contract with the user's dashboard; renaming one
    silently breaks it with the suite green.

## The Agent Review Loop (READ BEFORE ROUND 1)

Four personas (`.claude/agents/`) review this codebase in rounds. **The goal
is zero findings, not a steady supply of them.** A round that finds nothing
is a success and the correct time to stop.

This is not hypothetical caution. The sibling project `pypowerpetdoor` ran
this exact loop for ten rounds and then had to spend a commit undoing it.
The audit (`git show f347321` there) measured the damage:

- **~80% of added lines were cruft.** Only ~950 lines fixed real defects,
  while `src/` grew 45% (51% of that prose) and tests grew **414%**.
- **The 100% coverage gate became an amplifier**, taxing every proposed
  defensive branch roughly 5:1 in new tests.
- **"By the final rounds the review was finding bugs in code the review
  itself had written."**
- `.claude/analysis/` reached **25,511 lines** of review reports.
- ~600 comment sites had to be rewritten to strip "round N / persona /
  finding-ID" narration.

### Rules for every round

1. **A finding must name a user-visible consequence.** Who is harmed, doing
   what, with which input? "This could theoretically..." is not a finding.
   If the answer is "a future maintainer might", it is not a finding either.
2. **A finding against code a previous round added is presumed invalid.**
   It is evidence the earlier change was wrong, not that a new change is
   needed. Prefer reverting the earlier change to layering a fix on it.
3. **Never change behaviour that shipped and works, on documentary grounds
   alone.** `pypowerpetdoor`'s `docs/protocol.md` is reverse-engineered from
   observation; the code has been proven against real doors. Twice an agent
   "fixed" the wire format to match the document and broke it - the
   `set_notifications` boolean change survived ten rounds and two adversarial
   refutation passes before a differential audit caught it.
4. **Never narrow what we accept from the door.** Tightening validation on
   the *read* path turned malformed-but-usable data into silently dropped
   data (3 schedules became 1). Strictness belongs on what we *send*.
5. **No review archaeology in the code.** Comments explain the rationale.
   They never say "round 4", "per security-analyst M2", or "finding L7".
6. **Count the cost.** If a fix adds more test lines than it removes risk,
   say so and let the owner decide. Ten defensive branches at 5:1 is a
   500-line tax for zero user-visible change.
7. **Analysis output is transitory.** Reports go in `.claude/analysis/`
   (gitignored) and are never committed.

### Grep for the other sites before calling a fix done

Rounds 3, 4 and 5 each found a multi-site fix that had landed at **N-1 of N
sites**: `!= "unavailable"` tightened at 7 of 8; `refresh_status()` pinned in
neither of its 2; `schedule_count` fixed at 1 of 2. Three rounds, three
times. When a fix applies to more than one place, search for the others
before moving on.

### `npx jest` from the repo root is not the frontend suite

It misses `tests/frontend/jest.config.js`, never loads `setup.js`, and fails
every card test in under a second on `ReferenceError: makeHass is not
defined`. During a mutation campaign that is the worst possible failure mode:
**every mutation scores "killed" and the card looks perfectly pinned.** Use
`npm test`.

### Stop rule

Stop when a round produces no finding that satisfies rule 1. If rounds start
producing findings only in recently-added code, **stop and audit instead**:
diff the whole effort against its starting commit and ask what fraction of
the added lines a user would ever notice.

## Git Usage Rules (Critical)

**Never use git commands to revert uncommitted changes.**

1. **No `git checkout` / `git restore` to undo changes** — they destroy ALL
   uncommitted changes in the file, including work you meant to keep.
2. **Manual fixes only**: fix mistakes by editing the file.
3. **Git revert only when explicitly requested** by the user.

## Transitory files

Plans, agent analysis and review residue are **not product**. They live under
`.claude/analysis/`, which is gitignored. Never commit them.

## Threat Model (read before "hardening" anything)

The integration dials **out** to a pet door on the user's own LAN; nothing
connects inward. There is no authentication in the door's protocol and none
can be added from this side.

What matters here, because it is correctness rather than security:

- Anything network-derived that reaches a log, a state attribute, or the card
  must be treated as untrusted: the door is a cheap embedded device and has
  been observed to send malformed frames (see issue #16, `keyerror 905`).
- The WebSocket API is the one inbound surface. It is reachable by any
  logged-in HA user, so every command validates its payload with voluptuous
  and mutating commands require admin.
- The Lovelace card renders device-supplied text. Never interpolate it into
  `innerHTML`.

Defending against a *hostile peer on the LAN* defends a scenario the user
cannot mitigate anyway; do not add machinery for it.
