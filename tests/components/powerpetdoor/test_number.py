# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""Number entities: the hold-open time and the two trigger voltages."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT, CONF_TIMEOUT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from powerpetdoor import CommandError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.powerpetdoor.const import (
    DEFAULT_HOLD_MAX,
    DEFAULT_HOLD_MIN,
    DEFAULT_HOLD_STEP,
    DOMAIN,
)

from .conftest import TEST_HOST, TEST_PORT

HOLD = "number.power_pet_door_hold_open_time"
TRIGGER = "number.power_pet_door_sensor_trigger_voltage"
SLEEP_TRIGGER = "number.power_pet_door_sleep_sensor_trigger_voltage"


@pytest.fixture(autouse=True)
def _enable_all(entity_registry_enabled_by_default: None) -> None:
    """The two voltage numbers are disabled by default."""


async def test_the_hold_open_time_reads_the_door_in_seconds(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """The facade already stores seconds, so this is a straight read."""
    assert float(hass.states.get(HOLD).state) == 4.0


async def test_setting_the_hold_open_time_sends_seconds_unchanged(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """No unit conversion on this one - a scale factor here would be silent."""
    await hass.services.async_call(
        "number", "set_value", {"entity_id": HOLD, "value": 6.0}, blocking=True
    )

    mock_door.set_hold_time.assert_awaited_once_with(6.0)


@pytest.mark.parametrize(
    ("entity_id", "prop", "method"),
    [
        (TRIGGER, "sensor_trigger_voltage", "set_sensor_trigger_voltage"),
        (SLEEP_TRIGGER, "sleep_sensor_trigger_voltage", "set_sleep_sensor_trigger_voltage"),
    ],
)
async def test_a_trigger_voltage_is_shown_in_volts_not_millivolts(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    entity_id: str,
    prop: str,
    method: str,
) -> None:
    """1500 mV on the wire is 1.5 V on the dashboard.

    HA's VOLTAGE device class means volts, and a "voltage" of 1500 V on a
    battery-powered pet door is nonsense on a graph - and would break any
    template comparing it against a threshold in volts.
    """
    setattr(mock_door, prop, 1500)
    for callback in mock_door._callbacks["on_settings_change"]:
        callback({})
    await hass.async_block_till_done()

    assert float(hass.states.get(entity_id).state) == 1.5


@pytest.mark.parametrize(
    ("entity_id", "method"),
    [
        (TRIGGER, "set_sensor_trigger_voltage"),
        (SLEEP_TRIGGER, "set_sleep_sensor_trigger_voltage"),
    ],
)
async def test_a_trigger_voltage_is_sent_back_in_whole_millivolts(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    entity_id: str,
    method: str,
) -> None:
    """The door takes an integer count of millivolts.

    `round`, not `int`: 0.9 V is 900 mV, and truncating the float 899.9999
    that 0.9 * 1000 actually produces would send 899. An int is also what
    the wire format requires - a float would be rejected by the door.
    """
    await hass.services.async_call(
        "number", "set_value", {"entity_id": entity_id, "value": 0.9}, blocking=True
    )

    getattr(mock_door, method).assert_awaited_once_with(900)
    sent = getattr(mock_door, method).await_args.args[0]
    assert isinstance(sent, int)


@pytest.mark.parametrize(
    ("entity_id", "method"),
    [
        (TRIGGER, "set_sensor_trigger_voltage"),
        (SLEEP_TRIGGER, "set_sleep_sensor_trigger_voltage"),
    ],
)
async def test_a_voltage_of_zero_is_sent_as_zero(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    entity_id: str,
    method: str,
) -> None:
    """The bottom of the declared range round-trips.

    0 is the boundary the entity's `native_min_value` names, and a
    conversion that fell over on it would only fail for the one user who
    disabled a sensor by dropping its threshold to nothing.
    """
    await hass.services.async_call(
        "number", "set_value", {"entity_id": entity_id, "value": 0.0}, blocking=True
    )

    getattr(mock_door, method).assert_awaited_once_with(0)


@pytest.mark.parametrize(
    ("entity_id", "method"),
    [
        (TRIGGER, "set_sensor_trigger_voltage"),
        (SLEEP_TRIGGER, "set_sleep_sensor_trigger_voltage"),
    ],
)
async def test_the_top_of_the_voltage_range_is_sent_as_five_thousand_millivolts(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    entity_id: str,
    method: str,
) -> None:
    """The other end of the declared range."""
    await hass.services.async_call(
        "number", "set_value", {"entity_id": entity_id, "value": 5.0}, blocking=True
    )

    getattr(mock_door, method).assert_awaited_once_with(5000)


@pytest.mark.parametrize("entity_id", [TRIGGER, SLEEP_TRIGGER])
async def test_a_voltage_outside_the_declared_range_is_refused(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    entity_id: str,
) -> None:
    """Home Assistant enforces the bounds before the door is reached.

    Asserted so the bounds are known to be doing something: an entity that
    declared no range would accept 6.0 and send 6000 mV to a 5 V input.
    """
    with pytest.raises(Exception, match="range"):
        await hass.services.async_call(
            "number", "set_value", {"entity_id": entity_id, "value": 6.0}, blocking=True
        )


@pytest.mark.parametrize(
    ("entity_id", "method"),
    [
        (HOLD, "set_hold_time"),
        (TRIGGER, "set_sensor_trigger_voltage"),
        (SLEEP_TRIGGER, "set_sleep_sensor_trigger_voltage"),
    ],
)
@pytest.mark.parametrize(
    "raised", [CommandError("out of range"), OSError("reset"), TimeoutError("no answer")]
)
async def test_a_value_the_door_refuses_is_reported_to_the_user(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    entity_id: str,
    method: str,
    raised: Exception,
) -> None:
    """A refused write raises rather than silently reverting on next refresh."""
    getattr(mock_door, method).side_effect = raised

    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            "number", "set_value", {"entity_id": entity_id, "value": 2.0}, blocking=True
        )

    assert err.value.translation_key == "command_failed"


# ---------------------------------------------------------------------------
# The hold-open bounds, which are user configuration rather than device facts
# ---------------------------------------------------------------------------


async def test_the_hold_open_bounds_come_from_the_entrys_options(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """The door's app offers 2-8s; people asked for the wider range.

    Pinned to the values in `mock_config_entry`, so an entity that ignored
    the options and used the module defaults would still differ.
    """
    attributes = hass.states.get(HOLD).attributes

    assert attributes["min"] == 2.0
    assert attributes["max"] == 8.0
    assert attributes["step"] == 2.0


async def test_a_second_door_gets_its_own_hold_open_bounds(
    hass: HomeAssistant,
    two_doors: tuple[MockConfigEntry, MagicMock, MockConfigEntry, MagicMock],
) -> None:
    """Regression for the bug named in number.py's comment.

    The bounds used to be assigned into the module-level NUMBERS table, so
    with two doors configured whichever set up LAST won for both - and the
    user's carefully widened range on one door silently applied to the
    other. Asserting both doors in one test is the only way to see it.
    """
    first = hass.states.get(HOLD).attributes
    second = hass.states.get("number.back_door_hold_open_time").attributes

    assert (first["min"], first["max"], first["step"]) == (2.0, 8.0, 2.0)
    assert (second["min"], second["max"], second["step"]) == (1.0, 30.0, 0.5)


async def test_an_entry_with_no_hold_options_falls_back_to_the_defaults(
    hass: HomeAssistant, mock_door: MagicMock
) -> None:
    """An entry created before these options existed still renders.

    Without the fallback the entity would have no bounds at all, which Home
    Assistant refuses to render - the failure the options flow's inverted
    range check also guards against.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Power Pet Door",
        unique_id=f"{TEST_HOST}:{TEST_PORT}",
        data={CONF_HOST: TEST_HOST, CONF_PORT: TEST_PORT, CONF_NAME: "Power Pet Door"},
        options={CONF_TIMEOUT: 5.0},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    attributes = hass.states.get(HOLD).attributes
    assert attributes["min"] == DEFAULT_HOLD_MIN
    assert attributes["max"] == DEFAULT_HOLD_MAX
    assert attributes["step"] == DEFAULT_HOLD_STEP


async def test_the_hold_open_time_accepts_the_bounds_themselves(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """Both endpoints of the configured range are valid values.

    The boundary that decides whether the range is inclusive. A user who
    configured 2-8 must be able to select 8, and an off-by-one here is only
    visible at the extremes.
    """
    await hass.services.async_call(
        "number", "set_value", {"entity_id": HOLD, "value": 2.0}, blocking=True
    )
    await hass.services.async_call(
        "number", "set_value", {"entity_id": HOLD, "value": 8.0}, blocking=True
    )

    assert [call.args[0] for call in mock_door.set_hold_time.await_args_list] == [2.0, 8.0]


async def test_a_hold_open_time_beyond_the_configured_range_is_refused(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """...and one step past the top is not.

    Asserted alongside the test above so the range is known to exclude
    something; a control that accepted everything would pass that one.
    """
    with pytest.raises(Exception, match="range"):
        await hass.services.async_call(
            "number", "set_value", {"entity_id": HOLD, "value": 9.0}, blocking=True
        )

    mock_door.set_hold_time.assert_not_awaited()


@pytest.mark.parametrize(
    ("entity_id", "expected"),
    # Seconds and VOLTS - the door speaks millivolts and the entities
    # convert, so 1500 mV is 1.5 V on the dashboard.
    [(HOLD, 4.0), (TRIGGER, 1.5), (SLEEP_TRIGGER, 0.9)],
)
async def test_the_numbers_stay_available_while_the_door_is_powered_off(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    entity_id: str,
    expected: float,
) -> None:
    """These are settings the door remembers while powered down.

    Hiding them would make a value the door is perfectly willing to change
    look broken - and the hold-open time is one people set while the door is
    off precisely because it is off.
    """
    mock_door.power = False
    for callback in mock_door._callbacks["on_settings_change"]:
        callback({})
    await hass.async_block_till_done()

    # The actual value, not merely "not unavailable": an entity reporting
    # `unknown` is exactly as broken to the user as one reporting
    # `unavailable`, and this assertion used to pass for both.
    state = hass.states.get(entity_id).state
    assert state not in ("unavailable", "unknown")
    assert float(state) == pytest.approx(expected)
