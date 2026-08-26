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
tests/                              Python suite
├── components/powerpetdoor/        Core-shaped: what a core PR would take
├── simulator/                      Against the library's real door simulator
├── fuzz/                           Randomised input (hypothesis)
├── frontend/                       The card, under jsdom
└── test_ci_gates.py                This repo's own CI invariants
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
| `tests/components/powerpetdoor/` | Unit tests, on Home Assistant's own test infrastructure |
| `tests/simulator/` | End-to-end against pypowerpetdoor's **real** door simulator over a real socket — the layer that catches the integration and the library disagreeing |
| `tests/fuzz/` | Randomised input (hypothesis) |
| `tests/frontend/` | The card, under jsdom |
| `tests/test_ci_gates.py` | Repository invariants that nothing else would notice |

`tests/components/powerpetdoor/` is deliberately the shape and the path Home
Assistant core uses, and is kept to exactly what core would accept — see
[Core readiness](#core-readiness). Its `conftest.py` is self-contained for
the same reason; `tests/simulator/` and `tests/fuzz/` import the door
doubles from it rather than the other way round.

`tests/conftest.py` holds a single fixture, the `enable_custom_integrations`
shim, and is the one file that exists purely because this ships outside
core.

Target is 100% line and branch coverage, reached **without** `tests/fuzz/` —
the deterministic suite must never lean on randomised coverage.

`pytest-socket` blocks real sockets everywhere except `tests/simulator/`,
which enables them deliberately and binds only to loopback.

## Core readiness

This integration is distributed through HACS and there is no plan to change
that. It is nevertheless kept in a state where submitting it to Home
Assistant core would be a move rather than a rewrite: platinum quality
scale, 100% coverage, strict typing, no integration dependencies, and the
core test layout above.

What a core submission would still have to change is mechanical and short:

| Change | Why it cannot already be done here |
|---|---|
| `custom_components/powerpetdoor/` → `homeassistant/components/powerpetdoor/` | HACS installs custom integrations to `custom_components/` |
| `from custom_components.powerpetdoor` → `from homeassistant.components.powerpetdoor`, throughout the tests | Follows the move above |
| `pytest_homeassistant_custom_component.common` → `tests.common`, `.syrupy` → `tests.syrupy` | That package exists to re-export core's test helpers to custom integrations; in core you import them directly |
| Delete `"version"` from `manifest.json` | HACS **requires** it; core **rejects** it. The one genuinely irreconcilable field |
| Delete `tests/conftest.py` | A core integration is not a custom one and has nothing to enable |
| Delete `translations/en.json` | Core generates translations from `strings.json`; only `strings.json` is checked in |
| Run core's `script.gen_requirements_all` | `pypowerpetdoor` has to reach `requirements_all.txt`, which core generates from manifests |
| Add the domain to core's `.strict-typing` | Already passes `disallow_untyped_defs`, so this only records it |
| Open a PR against `home-assistant/brands` | Icon and logo live in a separate repo for every integration |

Staying behind, because core has nowhere to put them: `hacs.json`,
`www/powerpetdoor-schedule-card.js`, this repo's workflows and `scripts/`,
and the `simulator/`, `fuzz/` and `frontend/` suites. The WebSocket API the
card talks to is ordinary core-acceptable code and would go; **the card
itself would keep shipping from here**, which is the only reason a core
submission would not be the end of this repository.

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
