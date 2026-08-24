# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Breaking

- **Entity names and IDs have changed.** Every entity now uses Home
  Assistant's `has_entity_name` with translated names, which is required for
  the platinum quality scale. Existing entities keep their history (unique
  IDs are unchanged), but **friendly names change and some entity IDs
  differ**. Check any automation, script or dashboard that references a
  Power Pet Door entity by ID.
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

### Fixed

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
  the door open; *Open and auto-close* is the timed open a pet gets. They
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

### Added

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

### Fixed
- Updated version number

## [0.4.5] - 2024-01-01

### Fixed
- Moved initialization in client.py

## [0.4.4] - 2023-12-31

### Fixed
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

[Unreleased]: https://github.com/corporategoth/ha-powerpetdoor/compare/0.4.6...HEAD
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
