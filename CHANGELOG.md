# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.5.1] - 2026-09-02

### Fixed

- **A door you switched off no longer reads "unknown".** Asked for its
  status while powered off, the door answers `DOOR_POWEROFF` - a state the
  library did not know, so `sensor.door_status` showed `unknown` and the
  log filled with warnings for as long as the door stayed off. Because an
  ENUM sensor's undeclared states are dropped from long-term statistics,
  that was a hole in the history rather than a blip - and being switched
  off is a state people stay in deliberately. It now reports **Powered
  off**, and counts as closed, because the flap is down.

- **A stale value is no longer served as current after an outage.** Two
  things went wrong together, and the second hid the first.

  A door that loses mains power comes back with its power flag reset to
  **on** - it does not persist off. Measured on a real door: set it false,
  pull the plug, and it answers `power_state: "true"` the moment it is
  back. So a user who had switched the door off in Home Assistant holds a
  cached `False` that is now the opposite of the truth. Because every
  powered entity keys its availability off that flag, the cover, the door
  status, the sensors and the schedules all read `unavailable` together -
  a device that looks broken while answering perfectly well.

  Correcting it needs a settings read, and the door drops requests - not as
  a fault, and no pacing prevents it. `PowerPetDoor.refresh()` gathers its
  steps with `return_exceptions=True`, so a dropped `GET_SETTINGS` was
  reported only to a log. Nothing in this integration could see it. The
  coordinator had one workaround already - calling `refresh_status()` first
  purely because it is the one call that raises - and that only proves the
  door is answering, not that the settings arrived; and the reconnect
  handler had another, marking itself healthy on the strength of a refresh
  whose result it could not read. Both pinned the stale value in place, and
  the reconnect also deferred the next poll a full refresh interval: 300
  seconds by default, and the options flow permits 86400.

  The fix is in the library, where the gap was:
  [pypowerpetdoor 0.5.1](https://github.com/corporategoth/py-powerpetdoor)
  returns the names of the refresh steps that did not land. The coordinator
  now asks, and decides by step - a lost `status` or `settings` fails the
  update, while the battery, the lifetime counters and the hardware version
  keep their cached values rather than blanking a dashboard that is almost
  entirely correct. Both workarounds are gone.

  The reconnect handler now requests a refresh through the coordinator
  rather than asserting health it never verified, so the healthy flag is
  cleared only by a read that actually happened. It is debounced, so a
  flapping door refreshes once and coalesces the rest.

### Changed

- **Requires pypowerpetdoor 0.5.1.** Two of that release's fixes reach a
  user directly. The toggle button no longer reverses a door that is still
  moving - `toggle()` used to test a state deliberately wider than "open",
  so a press while the flap was rising read as "open, so close it" and sent
  it back down mid-travel. And the door's clock, which the diagnostics
  download reports, now arrives as an aware datetime rather than a naive
  one interpreted in whatever timezone the reader happened to assume.

  The library also stopped sending two commands - `SET_SCHEDULE_LIST` and
  `SET_TIME` - that no door has ever implemented, and now refuses an IANA
  timezone name on the wire where the door only speaks POSIX. This
  integration used neither command and already converted before writing, so
  nothing here changed to accommodate them.

- **The integration no longer depends on Home Assistant's `schedule`
  component.** It imported three constants from it - the `from`/`to` keys
  and the weekday names that make up the schedule payload format - and that
  import made `schedule` a manifest dependency, so every installation
  loaded a helper component it never configured. The three constants are
  now defined in the integration itself. The payload format is unchanged
  and is still Home Assistant's, so automations calling
  `powerpetdoor.set_schedule`, the WebSocket API and the schedule card all
  keep working exactly as before.

  This also removes a way the integration could break on a Home Assistant
  upgrade: the import read that component's `const.py`, which carries no
  stability contract, and a rename there would have stopped the integration
  setting up at all - no entities, no card, no schedules.

### Internal

- **The dependency gate now refuses a push rather than reporting one.**
  `scripts/check_dependencies.py` runs with `--strict` at pre-push, so an
  available upgrade fails instead of printing - which is the exact
  condition Dependabot opens a pull request for, and Dependabot only ever
  sees what was pushed. Three things had to be fixed first, each of which
  had been answering "all clear" without having looked:

  - it resolved `uv` off `PATH`, and inside `uv run` that is **Home
    Assistant's** pinned uv rather than the developer's. The older one
    answers `lock --upgrade --dry-run` with a bare "Lockfile changes
    detected" whatever the answer is, so every run reported a phantom
    pending upgrade. It now uses `$UV`, which `uv run` exports for exactly
    this;
  - it read the prose in `pyproject.toml`'s dependency block as a
    requirement, because an apostrophe is a quote character to a regex:
    everything from "Home Assistant's" to "manifest.json's" parsed as a
    package named `s`, and the script exited 1 on every run;
  - it called an action pin stale whenever it differed from the newest
    tag, in either direction. `home-assistant/actions` last cut a release
    in 2020 and has developed on master since, so the pin everyone uses is
    six years *ahead* of "latest" - and under `--strict` the only
    available fix would have been a six-year regression.

  Two checks are new: the ruff pinned by `.pre-commit-config.yaml` must be
  the ruff `uv.lock` resolves, so the hook and CI cannot format differently;
  and the card's npm toolchain is checked too, since `dependabot.yml`
  watches that ecosystem and `uv` cannot see it.

- **Two more gates that could never pass.** `ha_matrix.py --check --quick`
  built a resolve-only document and compared it byte-for-byte against a
  matrix measured by running the suite; the two differ by construction, so
  the pre-push hook reported a current matrix as stale on every run and
  could only be skipped. It now checks what a quick probe can actually
  answer - that every committed pair still resolves - and says which one
  did not when it fails. And `check_dependencies.py` read the prose in
  `pyproject.toml`'s dependency block as a requirement, because an
  apostrophe is a quote character to a regex.

- The card's test toolchain moved to jest 30 and eslint 10. Its branch
  coverage floor rose from 95% to 99.7% with it - jest 30 counts 445
  branches where 29 counted 300, and the suite reaches 444 of them, so the
  old floor would have permitted a twenty-branch regression in silence.

- The Python tests moved to `tests/components/powerpetdoor/`, the layout
  Home Assistant core uses, so that submitting this integration upstream
  would be a move rather than a rewrite. `docs/development.md` records what
  such a submission would still have to change. Nothing about the shipped
  integration changes as a result.

## [0.5.0] - 2026-08-25

### Breaking

- **Entity names have changed.** Every entity now uses Home Assistant's
  `has_entity_name` with translated names, which is required for the
  platinum quality scale, so **friendly names change**. Existing entities
  are migrated in place and keep their history, their settings and their
  `entity_id`, so automations, scripts and dashboards that name them keep
  working. Entities that had no counterpart before are new, and Home
  Assistant names those itself - on 2026.8 and newer it prefixes a new
  entity's ID with the device's area, so a door in "Breakfast Area" gets
  `binary_sensor.breakfast_area_power_pet_door_inside_schedule`.
- **There are no longer Open and Close buttons.** They sent exactly what
  `cover.open_cover` and `cover.close_cover` send on
  `cover.power_pet_door_door`, so they were a second control for the same
  two actions. `Cycle` and `Toggle` remain, because a cover
  has no way to ask for either.
- **The `schedule.*` helper entities are gone.** Earlier versions created
  them by monkeypatching Home Assistant's core `schedule` integration at
  runtime. That is not supported by Home Assistant and cannot be made to
  work without patching core. Schedules are now
  `binary_sensor.<name>_inside_schedule` / `_outside_schedule`, which carry
  the whole schedule in their attributes. See `docs/schedules.md`.
- **`powerpetdoor.update_schedule` is now `powerpetdoor.set_schedule`**, and
  is an entity action targeting a schedule entity.
- **The connectivity binary sensor is now `switch.<name>_connection`.** It
  reports the same state and can also disconnect and reconnect.
- **YAML configuration has been removed.** Config entries only.
- Requires **Home Assistant 2025.4.0 or newer**, on Python 3.13 or 3.14.
  That grid is measured rather than declared - `scripts/ha_matrix.py`
  installs each (Python, Home Assistant) pair and runs the suite against
  it. Python 3.11 and 3.12 are not supported: no Home Assistant the
  integration passes against will run on them.

#- **Upgrading no longer duplicates every entity.** Entities used to be
  filed in the registry under the door's own protocol field names
  (`power_state`, `timersEnabled`, `sensorOnIndoorNotificationsEnabled`);
  they now use the entity's translation key, so a name in `strings.json`
  and a registry entry cannot drift apart. Without a migration Home
  Assistant read the new keys as new entities and filed them alongside the
  old ones - a second Power switch, a second Inside sensor, and so on, with
  every history, statistic and dashboard reference still pointing at the
  first, which no longer updated. The old entity is now renamed in place,
  which also leaves its `entity_id` alone. An upgrade that already ran once
  is repaired: the empty duplicate is discarded and the entity holding the
  history is kept.
- **The old "Cycle" button becomes Toggle, not the new Cycle.** It was
  labelled Cycle, but it opened the door when it read idle or closed and
  closed it when it read keepup or holding - a toggle. Mapping it onto the
  button that merely inherited its label would have silently changed what
  an existing automation does.
- **On an upgraded system the new Cycle button may be named
  `button.<name>_cycle_2`.** Home Assistant builds an entity id once,
  from the name, and the old button already holds `_cycle` - it is now
  Toggle, and it keeps that id so existing automations and dashboards
  that press it still work. A fresh install has no such clash and gets
  a plain `_cycle`.
- **The two dead `schedule.*` entities are removed on upgrade** rather than
  left reading `unavailable` forever. The monkeypatch that set their state
  is gone, and their replacements are `binary_sensor` entities, which a
  registry entry cannot be renamed into.
- **No more "please create a bug report" warning at every startup.** The
  library reads its own translation file the first time it logs a
  translated message, and building the door logs one, so Home Assistant
  detected a blocking file read on the event loop and told the user to file
  a bug against this integration. The table is now warmed in the executor
  first.
## Fixed

- **Saving any schedule edit no longer rewrites the door's all-day entries.**
  A whole day was reported to Home Assistant as `00:00-00:00`, so a factory
  door's own `00:00-23:59` entry did not survive a read-modify-write and
  every save pushed a changed entry back. Worse, `00:00-00:00` is a spelling
  a real door stores and then **never acts on** - measured against firmware
  1.7.18 - so the entry written for "always on" would have switched the
  sensors off.
- **A window that ends before it starts is no longer reported as if it were
  open.** Measured against a real door: such an entry does not wrap round
  within the day, and does not spill into the next morning either. The door
  keeps it and never acts on it. Home Assistant previously drew it as two
  windows and reported the sensor on for hours it was actually off. Saving
  one is now refused, with a message pointing at the two-window spelling
  that does work (`22:00` to end of day, then `00:00-06:00` the next day).
- **A window whose start equals its end is no longer reported as "all day".**
  On a real door it gates the sensor off completely.
- `00:00` written as a window *end* now means the end of the day, as anyone
  writing it intends, and reaches the door as `24:00` - which the device is
  measured to honour and to preserve. A `00:00` *start* is untouched: the
  rule is positional.
- `23:59` is no longer treated as the end of the day. It is the last minute
  of the day, so a window ending there is a minute short - which is what it
  says, and what the door does with it. Doors set up by the vendor app often
  carry `00:00-23:59`; that entry is now reported as it stands and is no
  longer rewritten by an edit made to some other day.
- **The schedule sensors now follow the `Schedule enabled` switch.** With the
  door's schedule engine off it consults no window at all, so reporting a
  closed window contradicted the switch beside it while the pet walked
  through.
- **Changing a door's address no longer duplicates every entity.** Both the
  device and every entity are identified by `host:port`, so a reconfigure
  used to create a second device and 34 more entities suffixed `_2`, leaving
  every dashboard, automation and statistic pointing at entities that no
  longer existed. A DHCP lease was enough to trigger it.
- **The door status sensor no longer reads `unknown` on every close.** A real
  door reports three closing states and the library only knew two, so each
  time the flap came down the cover was briefly neither open nor closing, the
  status sensor showed `unknown`, and a warning was logged. Measured against
  firmware 1.7.18 by cycling a physical door; the new `closing` state is
  declared and translated, so it also stops being dropped from long-term
  statistics.
- **Entities come back the moment the door reconnects**, not on the next
  poll. Any outage longer than the refresh interval guaranteed one failed
  poll, and nothing cleared that until the next scheduled one - so after a
  router reboot or a power cut the whole dashboard stayed `unavailable` for
  up to a full refresh interval (300 seconds by default, and the options
  flow permits 86400) after Home Assistant was demonstrably talking to the
  door again.
- **A `set_schedule` action naming both schedule entities no longer loses one
  of the writes.** The door holds ONE table covering both sensors, so the two
  calls ran concurrently, each rebuilt the other kind from the same pre-edit
  table, and the last one to finish resurrected the other's old windows. The
  action reported success and nothing was logged. Targeting the *device* -
  which is what the visual action editor produces - lost a write the same
  way. Schedule writes are now serialised per door, which also closes the
  case of a card save landing in the middle of an automation's edit.
- **The card now says when schedules are switched off on the door.** With the
  `Schedule enabled` switch off the door consults no window at all and both
  sensors stay live, but the card still drew the stored windows - implying a
  restriction that was not being applied, and letting the user edit a
  schedule that could not take effect.
- **Disabling an entity can no longer take the integration offline**
  ([#18](https://github.com/corporategoth/ha-powerpetdoor/issues/18)).
  Disabling the *Latency* sensor used to make everything unavailable,
  because the connection was owned by an entity. The connection now belongs
  to the integration and is established during setup, so no entity is
  load-bearing. A regression test disables every entity and asserts the door
  stays connected.
- **`KeyError` on a late reply**
  ([#16](https://github.com/corporategoth/ha-powerpetdoor/issues/16)). Fixed
  in pypowerpetdoor; the bundled protocol client that caused it no longer
  exists here.
- **Two doors no longer interfere with each other.** Hold-open bounds were
  written into a module-level table, so a second door's options overwrote the
  first's.
- **The Open button no longer closes the door by itself.** *Open* now holds
  the door open; *Cycle* is the timed open a pet gets. They
  were previously the same command, so one of the two behaviours was
  unreachable. Requires pypowerpetdoor 0.4.1, where `open()` means "open and
  stay open" and `cycle()` is the timed open.
- **Battery reports "unknown" rather than 0%** when no battery is fitted, so
  it no longer triggers low-battery automations on a mains-only door.
- The card's header and console banner disagreed about its version (1.6.0
  vs 1.5.0), and it contained two unused-variable bugs.
- **The schedule card is usable without a mouse and with a screen reader.**
  It previously had no keyboard path and no ARIA at all: a grid of
  unlabelled divs. Windows and day columns are now focusable and announce
  their day and both times, the edit dialog is a native `<dialog>` with
  focus management and Escape, and read-only users get a card that says so
  instead of one whose every save fails.
- **A short window is no longer a 6px click target**, which made the card
  effectively unusable on a phone, and all-day and overnight windows are
  drawn at their real length rather than as 14px stubs.
- **The first edit on a door with no schedule works.** The card synthesised
  an invalid `24:00`, so the very first change a new user made was always
  rejected.
- **The `set_schedule` action's description now renders in the UI.** It
  carried a JSON example inline, and Home Assistant reads `{...}` in any
  translated string as a placeholder that must be an identifier - so the
  whole description was rejected. The same example is still shown, from the
  `example:` block in `services.yaml` where it belongs.

#- **The schedule card can copy a schedule again.** Both ways it used to,
  before the rewrite dropped them: "copy from the other sensor" under the
  grid, and clicking a day's heading to copy that day onto any others.
- **Dragging a window into its neighbour merges them.** The edge stops at
  the neighbour's border, and letting go there makes one window of the two.
  Drag clear past the neighbour and it is drawn in the removal colour -
  releasing then absorbs it. Previously the edge sailed straight through
  and the save produced two overlapping windows.
## Added

- **Platinum quality scale**, tracked rule by rule in `quality_scale.yaml`.
- **`powerpetdoor.set_schedule` action**, so automations can change a
  schedule — previously only the Lovelace card could
  ([#19](https://github.com/corporategoth/ha-powerpetdoor/pull/19)).
- **`schedule_entries` attribute**: a readable summary such as
  `["Mon, Wed, Fri: 06:00-20:00"]`, grouped by window (also #19).
- **`next_event` attribute** on the schedule sensors, and a timer so they
  change state punctually rather than at the next poll.
- **Diagnostics download**, with the host redacted.
- **Reconfigure flow**, for moving a door to a new address without losing
  history.
- **New entities**: door status (raw state machine), mains power, battery
  charging, remote paired / remote key, door clock, and Close / Toggle
  buttons.
- **Translations**: every user-facing string, including the Lovelace card,
  which now carries its own catalogue.
- **Documentation** split into `docs/` — installation, entities, schedules,
  troubleshooting and development.

### Changed

- Rewritten on `pypowerpetdoor`'s high-level `PowerPetDoor` interface. The
  integration no longer touches the protocol client or the wire format.
- State is pushed from the door rather than polled; the refresh interval is
  now only a safety net.
- The Notify switches are documented as controlling the **manufacturer's
  app** notifications, not Home Assistant's
  ([#8](https://github.com/corporategoth/ha-powerpetdoor/issues/8)).
- Now installable from the **HACS default repository** rather than as a
  custom repository.

## [0.4.6] - 2025-01-05

### Added
- Description and title to config flow

### Changed
- Changed to use CoverEntityFeature enum

#- **Platinum is now what Home Assistant's own validator says, not just what
  the manifest claims.** hassfest's quality-scale plugin returns immediately
  for a non-core integration, so the file it exists to validate was never
  opened in CI. Run against a core-mode copy it reported that Bronze was not
  met - and therefore neither was Platinum - because three of the 54 rules
  (`common-modules`, `docs-conditions`, `docs-triggers`) were simply absent
  and every rule key is required. All 54 are present now, and the rule list
  is pinned in `tests/test_ci_gates.py` so an upstream addition cannot go
  unnoticed again.
- **`tzdata` is no longer a declared requirement.** The platinum
  `strict-typing` rule requires every entry in `manifest.json`'s
  `requirements` to ship `py.typed`; `tzdata` does not, and there is no
  `types-tzdata`. Nothing in this integration imports it - `pypowerpetdoor`
  does - so the floor moved there, and 0.4.3 raises it to `tzdata>=2026.3`,
  which is the version this used to pin. Users still get a current IANA
  database; the door still gets correct DST rules.
- **The `set_schedule` action has an icon**, so it no longer renders as a
  generic cog in the action picker.
## Fixed
- Updated version number

## [0.4.5] - 2024-01-01

#- **The Door clock sensor actually reads the door's clock.** It reported
  `unknown` from the moment it was created and never changed, because
  nothing asked the door for the time. The clock is what schedules are
  evaluated against, so a door whose clock or timezone has drifted opens on
  the wrong schedule with nothing else to show for it - which is the entire
  reason to expose it.
- **The Remote paired and Remote key set sensors report the door's answer**
  rather than `off`. Nothing had ever queried the pairing, so both showed a
  made-up value, which is worse than showing none. Read once per
  connection, since pairing is static.
## Fixed
- Moved initialization in client.py

## [0.4.4] - 2023-12-31

#- **The Door clock and the two Remote sensors are gone.** All three reported
  a value nothing had ever fetched - the clock read `unknown` forever, and
  the remote sensors read `off`, which is a made-up answer rather than a
  missing one. Polling them was the wrong fix: a clock is misleading the
  moment it is a refresh interval out of date, and the remote pairing is a
  phone-app concern Home Assistant can neither use nor change. Both values
  are still in the **diagnostics download**, where they are read fresh at
  the moment it is taken, which is when they are actually worth having.
## Fixed
- Fixed multiple doors sharing same state and listeners (PR #11 by @sushantsaxena)
- Move initialization to constructor to fix state isolation

## [0.4.3] - 2023-08-08

### Fixed
- Fixed init problem

## [0.4.2] - 2023-08-06

### Fixed
- Fixed typo

## [0.4.1] - 2023-08-06

### Fixed
- Stop trying to update the mappingproxy

## [0.4.0] - 2023-07-30

### Added
- Schedule entity with compression of schedule entries
- Many more sensors, switches, and numbers
- Issue templates
- More complete door functionality handling

### Changed
- Updated switches to store actual bools
- Fixed client side code
- Cleaned up the implementation
- Changed the way coordinators work
- Updated README with more information and shields

### Fixed
- Fixed disabled entries by default
- Fixed config flow issues

## [0.4.0-beta2] - 2023-05-23

### Changed
- Beta release with schedule improvements

## [0.4.0-beta1] - 2023-05-17

### Added
- Initial schedule entity implementation

## [0.3.2] - 2023-05-10

### Changed
- Battery updates properly with callback
- Disable active controls while power is off
- Categorize config/diagnostic entities

## [0.3.1] - 2023-05-10

### Changed
- Removed 'stop' support
- Added 'closing' and 'opening' status
- Updated manifest for hassfest

## [0.3.0] - 2023-05-10

### Changed
- Changed the door to a cover entity
- Added a button to open/close
- Updated manifest for hassfest

## [0.2.7] - 2023-02-14

### Changed
- Changed from async_setup_platforms

## [0.2.6] - 2023-02-12

### Added
- HACS and Home Assistant workflows

### Fixed
- Fixed minimum time between command sends

## [0.2.5] - 2022-03-22

### Added
- Retry logic
- Do not disconnect on lack of response

## [0.2.4] - 2022-03-19

### Fixed
- Fixed options screen
- Updated detailed status fields

## [0.2.3] - 2022-03-19

### Changed
- More objects now use data coordinator

## [0.2.2] - 2022-03-18

### Fixed
- Updated config so options work
- Updated manifest

## [0.2.1] - 2022-03-18

### Added
- Options flow
- Queue for sending messages

### Changed
- New way of handling schemas
- Updated README

## [0.2.0] - 2022-03-04

### Added
- Config flow support
- Firmware and battery information
- Latency sensor
- Logo

### Changed
- Door entity switch state now uses open/opening/close/closing
- Changed to use sync callbacks for notifications
- Added timeouts for running code and validation to config

### Fixed
- Fixed unique ID
- Allow more than one ping fail
- Fixed double-connect on reconnect
- Don't let keepalive and settings timers multiply
- Futures clean themselves up

## [0.1.7] - 2022-03-02

### Added
- Filter on entities

## [0.1.6] - 2022-03-02

### Fixed
- Multiple fixes for entity schema and door schema
- Fixed return value for state
- Added __init__.py files

## [0.1.5] - 2022-02-28

### Changed
- Renamed hcas -> hacs
- Changed to use proper service calls

## [0.1.4] - 2022-02-28

### Added
- Auto (timers) support

## [0.1.3] - 2022-02-28

### Added
- Initial release
- Basic sensor reading and settings refresh
- Door status command
- Last change tracking
- Support for hold time configuration

[Unreleased]: https://github.com/corporategoth/ha-powerpetdoor/compare/0.5.1...HEAD
[0.5.1]: https://github.com/corporategoth/ha-powerpetdoor/compare/0.5.0...0.5.1
[0.5.0]: https://github.com/corporategoth/ha-powerpetdoor/compare/0.4.6...0.5.0
[0.4.6]: https://github.com/corporategoth/ha-powerpetdoor/compare/0.4.5...0.4.6
[0.4.5]: https://github.com/corporategoth/ha-powerpetdoor/compare/0.4.4...0.4.5
[0.4.4]: https://github.com/corporategoth/ha-powerpetdoor/compare/0.4.3...0.4.4
[0.4.3]: https://github.com/corporategoth/ha-powerpetdoor/compare/0.4.2...0.4.3
[0.4.2]: https://github.com/corporategoth/ha-powerpetdoor/compare/0.4.1...0.4.2
[0.4.1]: https://github.com/corporategoth/ha-powerpetdoor/compare/0.4.0...0.4.1
[0.4.0]: https://github.com/corporategoth/ha-powerpetdoor/compare/0.3.2...0.4.0
[0.4.0-beta2]: https://github.com/corporategoth/ha-powerpetdoor/compare/0.4.0-beta1...0.4.0-beta2
[0.4.0-beta1]: https://github.com/corporategoth/ha-powerpetdoor/compare/0.3.2...0.4.0-beta1
[0.3.2]: https://github.com/corporategoth/ha-powerpetdoor/compare/0.3.1...0.3.2
[0.3.1]: https://github.com/corporategoth/ha-powerpetdoor/compare/0.3.0...0.3.1
[0.3.0]: https://github.com/corporategoth/ha-powerpetdoor/compare/0.2.7...0.3.0
[0.2.7]: https://github.com/corporategoth/ha-powerpetdoor/compare/0.2.6...0.2.7
[0.2.6]: https://github.com/corporategoth/ha-powerpetdoor/compare/0.2.5...0.2.6
[0.2.5]: https://github.com/corporategoth/ha-powerpetdoor/compare/0.2.4...0.2.5
[0.2.4]: https://github.com/corporategoth/ha-powerpetdoor/compare/0.2.3...0.2.4
[0.2.3]: https://github.com/corporategoth/ha-powerpetdoor/compare/0.2.2...0.2.3
[0.2.2]: https://github.com/corporategoth/ha-powerpetdoor/compare/0.2.1...0.2.2
[0.2.1]: https://github.com/corporategoth/ha-powerpetdoor/compare/0.2.0...0.2.1
[0.2.0]: https://github.com/corporategoth/ha-powerpetdoor/compare/0.1.7...0.2.0
[0.1.7]: https://github.com/corporategoth/ha-powerpetdoor/compare/0.1.6...0.1.7
[0.1.6]: https://github.com/corporategoth/ha-powerpetdoor/compare/0.1.5...0.1.6
[0.1.5]: https://github.com/corporategoth/ha-powerpetdoor/compare/0.1.4...0.1.5
[0.1.4]: https://github.com/corporategoth/ha-powerpetdoor/compare/0.1.3...0.1.4
[0.1.3]: https://github.com/corporategoth/ha-powerpetdoor/releases/tag/0.1.3
