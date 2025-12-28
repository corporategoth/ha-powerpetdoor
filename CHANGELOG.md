# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Comprehensive simulator-based integration tests
- Timezone select entity for door configuration
- Schedule calendar card support
- Priority queue for message handling
- Test framework using pypowerpetdoor simulator

### Changed
- Updated to use pypowerpetdoor v0.3.0+ from PyPI
- Removed client.py wrapper, now imports directly from powerpetdoor
- Added pyproject.toml and uv.lock for uv package management

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
