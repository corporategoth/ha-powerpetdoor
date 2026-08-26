# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""Sensor entities: read-only values from the door."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from homeassistant.core import HomeAssistant
from powerpetdoor import BatteryInfo, DoorStatus
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components import powerpetdoor as powerpetdoor_component

BATTERY = "sensor.power_pet_door_battery"
LATENCY = "sensor.power_pet_door_latency"
STATUS = "sensor.power_pet_door_door_status"
#: The shipped file, found from the imported package rather than from a
#: repo-relative path. This suite moved once already, into the layout Home
#: Assistant core uses, and a counted chain of `.parent` would have broken
#: silently-looking - it reads a file, so the failure is a missing file, not
#: a wrong answer.
STRINGS = Path(powerpetdoor_component.__file__).parent / "strings.json"
OPEN_CYCLES = "sensor.power_pet_door_total_open_cycles"
AUTO_RETRACTS = "sensor.power_pet_door_total_auto_retracts"


@pytest.fixture(autouse=True)
def _enable_all(entity_registry_enabled_by_default: None) -> None:
    """Three of the six are disabled by default."""


def push(door: MagicMock) -> None:
    """Fire the door's settings-change callbacks, as a real push would."""
    for callback in door._callbacks["on_settings_change"]:
        callback({})


async def test_the_battery_sensor_reports_the_charge_level(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """A fitted battery reports its percentage."""
    mock_door.battery = BatteryInfo(percent=64, present=True, ac_present=True)
    push(mock_door)
    await hass.async_block_till_done()

    assert hass.states.get(BATTERY).state == "64"


async def test_a_door_with_no_battery_fitted_reports_no_reading(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """Not 0%, which is a flat battery and a different fact entirely.

    A mains-only door reports 0 on the wire. Publishing that would show a
    dead battery on every dashboard and fire every low-battery automation,
    for a door that has no battery to be low.
    """
    mock_door.battery = BatteryInfo(percent=0, present=False, ac_present=True)
    push(mock_door)
    await hass.async_block_till_done()

    assert hass.states.get(BATTERY).state == "unknown"


async def test_a_genuinely_flat_fitted_battery_reports_zero(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """The other side of that boundary, and the one that matters most.

    `present` is what decides, not the percentage - so a fitted battery at
    0% must still publish 0 and set off the alarm it should.
    """
    mock_door.battery = BatteryInfo(percent=0, present=True, ac_present=False)
    push(mock_door)
    await hass.async_block_till_done()

    assert hass.states.get(BATTERY).state == "0"


async def test_the_battery_sensor_is_a_battery(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Device class and unit, which drive the icon ladder and statistics."""
    attributes = hass.states.get(BATTERY).attributes

    assert attributes["device_class"] == "battery"
    assert attributes["unit_of_measurement"] == "%"
    assert attributes["state_class"] == "measurement"


async def test_the_latency_sensor_reports_the_round_trip_in_milliseconds(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """Issue #18 was reported by users who disabled exactly this entity."""
    # The library reports seconds; the sensor displays milliseconds.
    mock_door.latency = 0.0475
    push(mock_door)
    await hass.async_block_till_done()

    state = hass.states.get(LATENCY)
    assert float(state.state) == 47.5
    assert state.attributes["unit_of_measurement"] == "ms"


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (DoorStatus.IDLE, "idle"),
        (DoorStatus.CLOSED, "closed"),
        (DoorStatus.RISING, "rising"),
        (DoorStatus.SLOWING, "slowing"),
        (DoorStatus.HOLDING, "holding"),
        (DoorStatus.KEEPUP, "keepup"),
        (DoorStatus.CLOSING, "closing"),
        (DoorStatus.CLOSING_TOP_OPEN, "closing_top_open"),
        (DoorStatus.CLOSING_MID_OPEN, "closing_mid_open"),
        (DoorStatus.UNKNOWN, "unknown"),
    ],
)
async def test_every_door_state_is_reported_by_its_own_name(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    status: DoorStatus,
    expected: str,
) -> None:
    """Pinned by literal, one row per state.

    These strings are enum options in `strings.json` and are what a template
    or an automation compares against. HOLDING and KEEPUP both read as
    "open" on the cover, so this sensor is the only place the difference is
    visible - which is what a bug report needs.
    """
    mock_door.status = status
    for callback in mock_door._callbacks["on_status_change"]:
        callback(status)
    await hass.async_block_till_done()

    assert hass.states.get(STATUS).state == expected


async def test_the_status_sensor_declares_every_state_it_can_report(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """An ENUM sensor reporting a state it did not declare is invalid.

    Home Assistant logs the state as invalid and long-term statistics drop
    it, so a state added to the library and not to `options` silently
    disappears from history.
    """
    options = hass.states.get(STATUS).attributes["options"]

    assert set(options) == {status.name.lower() for status in DoorStatus}
    assert "keepup" in options
    assert "unknown" in options
    # A real door reports THREE closing states, and "closing" - the motor
    # starting before the flap moves - is the one that was missing from the
    # library entirely. Every close produced an undeclared state.
    assert {"closing", "closing_top_open", "closing_mid_open"} <= set(options)


async def test_every_state_the_sensor_declares_has_a_translation(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Options come from the library; the names come from us.

    So a state added upstream appears in `options` automatically and is then
    shown to the user as a raw key like `closing_top_open` unless someone
    remembers `strings.json`. Deriving one side and hand-writing the other is
    exactly the split that needs a gate, and this is it.
    """
    strings = json.loads(STRINGS.read_text(encoding="utf-8"))
    translated = strings["entity"]["sensor"]["status"]["state"]

    assert set(hass.states.get(STATUS).attributes["options"]) == set(translated)


@pytest.mark.parametrize(
    ("entity_id", "prop", "value"),
    [
        (OPEN_CYCLES, "total_open_cycles", 4321),
        (AUTO_RETRACTS, "total_auto_retracts", 17),
    ],
)
async def test_the_lifetime_counters_report_their_own_totals(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    entity_id: str,
    prop: str,
    value: int,
) -> None:
    """Two counters that are easy to wire to each other."""
    setattr(mock_door, prop, value)
    push(mock_door)
    await hass.async_block_till_done()

    assert hass.states.get(entity_id).state == str(value)


@pytest.mark.parametrize("entity_id", [OPEN_CYCLES, AUTO_RETRACTS])
async def test_the_lifetime_counters_are_total_increasing(
    hass: HomeAssistant, setup_integration: MockConfigEntry, entity_id: str
) -> None:
    """A door reset takes these back to zero without it being a real drop.

    TOTAL_INCREASING is what tells the statistics engine to treat that as a
    counter reset rather than as negative usage.
    """
    assert hass.states.get(entity_id).attributes["state_class"] == "total_increasing"


@pytest.mark.parametrize("entity_id", [BATTERY, LATENCY, STATUS, OPEN_CYCLES, AUTO_RETRACTS])
async def test_every_sensor_stays_available_while_the_door_is_powered_off(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    entity_id: str,
) -> None:
    """The door keeps answering while powered off, so these keep reporting.

    Battery and latency in particular are MORE interesting with the motor
    off, not less - a door powered down on a flat battery is precisely when
    someone looks.
    """
    mock_door.power = False
    push(mock_door)
    await hass.async_block_till_done()

    # The actual reading, not merely "not unavailable". An entity reporting
    # `unknown` is exactly as broken to the user as one reporting
    # `unavailable`, and this assertion used to pass for both - which is the
    # very outcome the docstring above says must not happen.
    state = hass.states.get(entity_id).state
    assert state not in ("unavailable", "unknown")


@pytest.mark.parametrize("entity_id", [BATTERY, LATENCY, STATUS, OPEN_CYCLES, AUTO_RETRACTS])
async def test_every_sensor_goes_unavailable_when_the_door_is_unreachable(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    entity_id: str,
) -> None:
    """The other side of availability: a lost door is not a stale reading.

    Without this, a door that dropped off would keep showing the last
    battery percentage it reported, indefinitely and with no sign it was
    historic.
    """
    mock_door.connected = False
    for callback in mock_door._callbacks["on_disconnect"]:
        callback()
    await hass.async_block_till_done()

    assert hass.states.get(entity_id).state == "unavailable"
