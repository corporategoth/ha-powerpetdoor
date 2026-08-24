# Development

## Setup

```bash
git clone https://github.com/corporategoth/ha-powerpetdoor
cd ha-powerpetdoor
./scripts/setup-dev.sh
```

That creates the virtualenv, installs Python and Node dev dependencies, and
installs the git hooks. [uv](https://docs.astral.sh/uv/) is used if present;
otherwise it falls back to pip.

With [direnv](https://direnv.net/), `direnv allow` activates the venv on
`cd`.

## Day to day

```bash
uv run pytest                              # the Python suite
uv run pytest --cov                        # ...with the 100% coverage gate
uv run ruff check custom_components tests scripts
uv run mypy custom_components
npm test                                   # the Lovelace card, under jsdom
npm run lint                               # the card
uv run python scripts/check_translations.py --untranslated
```

The pre-commit hook runs lint, types, the fast tests and the translation
checks. The pre-push hook additionally runs the full suite with the coverage
gate, the dependency audit and the matrix check.

## Layout

```
custom_components/powerpetdoor/
├── __init__.py          Entry setup/unload
├── coordinator.py       Owns the PowerPetDoor connection; runtime_data
├── entity.py            Shared base classes
├── config_flow.py       Setup, reconfigure and options flows
├── binary_sensor.py     Diagnostics + the two schedule sensors + set_schedule
├── button.py  cover.py  number.py  select.py  sensor.py  switch.py
├── schedule.py          Schedule maths and the single write path
├── websocket.py         The API the Lovelace card calls
├── diagnostics.py       Diagnostics download
├── tz_utils.py          Timezone helpers over the library's
├── strings.json         The translation catalogue (source of truth)
├── translations/en.json Generated from strings.json — do not hand-edit
├── icons.json           Entity and state icons
├── services.yaml        The set_schedule action
└── quality_scale.yaml   Quality-scale status, rule by rule

www/powerpetdoor-schedule-card.js   The Lovelace card (plain browser JS)
scripts/                            Repo tooling — see below
tests/                              Python suite; tests/frontend/ is the card
```

### The library boundary

All protocol work lives in
[pypowerpetdoor](https://github.com/corporategoth/py-powerpetdoor). This
integration talks to the door only through `powerpetdoor.PowerPetDoor`, the
high-level facade — never `PowerPetDoorClient`, and never the wire protocol.

If something needs a new command, a new field, or different protocol
behaviour, **the fix belongs in the library**. Adding raw protocol handling
here is a design failure, not a shortcut.

## Supported versions

The supported `(Python, Home Assistant)` grid is **measured, not declared**.
Home Assistant's `Requires-Python` is only a floor; an old Home Assistant
also pins old transitive dependencies that have no wheels for a *new*
interpreter. So each interpreter has both an oldest and a newest Home
Assistant that actually installs and passes.

```bash
uv run python scripts/ha_matrix.py             # probe by RUNNING the suite (slow, ~15 min)
uv run python scripts/ha_matrix.py --quick     # resolve-only; much faster, but optimistic
uv run python scripts/ha_matrix.py --write     # ...and update the committed matrix
uv run python scripts/ha_matrix.py --check     # fail if the committed matrix is stale
```

The result lives in `.github/ha-matrix.json` and the CI workflow builds its
job matrix from it. Re-run it when a new Home Assistant lands, a new CPython
lands, or you start using an API older versions lack.

Two rules:

1. **Platinum beats reach.** If supporting an older Home Assistant would
   forfeit a quality-scale rule, drop the older Home Assistant. `runtime_data`
   is a bronze requirement and arrived in HA 2024.6; `_get_reconfigure_entry`
   in 2024.11. Measured against the real suite, the floor lands at HA 2025.4.0
   on Python 3.13 — so Python 3.11 and 3.12 are unsupported, because no Home
   Assistant they can run passes.
2. **Never widen support by contorting the code.** No `hasattr` probes, no
   version sniffing, no compatibility shims.

`hacs.json`'s minimum must equal the matrix's — `tests/test_ci_gates.py`
asserts it.

## Repository tooling

| Script | What it answers |
|---|---|
| `scripts/ha_matrix.py` | Which (Python, Home Assistant) pairs actually work |
| `scripts/check_translations.py` | Dangling `translation_key`s, orphaned or missing locale entries, placeholder mismatches, and user-facing text that never entered the system — in Python *and* in the card |
| `scripts/check_dependencies.py` | Lock consistency, available upgrades, action pins, and advisories (split by whether we can act on them — most of the tree is pinned by Home Assistant, not by us) |
| `scripts/check_card_version.py` | That the card's header and console banner agree, and that a changed card got a new version |
| `scripts/generate_gaps_report.py` | Coverage gaps, written to `tests/TESTING_GAPS.md` |

## Translations

`strings.json` is the catalogue. `translations/en.json` is **generated** from
it:

```bash
uv run python scripts/check_translations.py --write-en
```

Never hand-edit `en.json` — Home Assistant reads *it*, not `strings.json`, at
runtime, so a key added only to `strings.json` silently renders as a raw key
in the UI.

The card carries its own catalogue (`const STRINGS` at the top of
`powerpetdoor-schedule-card.js`), because Home Assistant's translation
machinery covers integrations, not custom cards. Add a language by adding a
key to that object; anything it omits falls back to English.

## Tests

| Location | What it covers |
|---|---|
| `tests/test_*.py` | Unit tests, on Home Assistant's own test infrastructure |
| `tests/simulator/` | End-to-end against pypowerpetdoor's **real** door simulator over a real socket — the layer that catches the integration and the library disagreeing |
| `tests/fuzz/` | Randomised input (hypothesis) |
| `tests/frontend/` | The card, under jsdom |
| `tests/test_ci_gates.py` | Repository invariants that nothing else would notice |

Target is 100% line and branch coverage, reached **without** `tests/fuzz/` —
the deterministic suite must never lean on randomised coverage.

`pytest-socket` blocks real sockets everywhere except `tests/simulator/`,
which enables them deliberately and binds only to loopback.

## Quality scale

`custom_components/powerpetdoor/quality_scale.yaml` tracks every rule. A rule
is `done`, or `exempt` **with a comment explaining why**. `tests/test_ci_gates.py`
fails on an unexplained exemption.

Things that would fail Home Assistant review — do not reintroduce:

- Monkeypatching another integration (see
  [schedules.md](schedules.md#why-not-the-core-schedule-helper)).
- YAML platform setup. Config entries only.
- Blocking I/O on the event loop.
- Bare `except:`.
- A hardcoded `_attr_name` on an entity.

## Releasing

Do not tag until the maintainer says so.

1. `scripts/ha_matrix.py --write`, and commit if it moved.
2. Update `manifest.json`'s `version`.
3. Update `CHANGELOG.md`.
4. If the card changed, bump its version in **both** the header comment and
   the console banner (`scripts/check_card_version.py` enforces this).
5. Confirm `hacs.json`'s minimum matches the matrix.
6. Tag.
