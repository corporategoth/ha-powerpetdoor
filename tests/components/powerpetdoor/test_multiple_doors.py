# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""Two doors configured at once must not see or affect each other.

Plenty of people have more than one Power Pet Door, and this integration has
got it wrong before: issue #9 ("Incorrect device state when using more than
one Power Pet Door") and PR #11 were both shared state between doors, and
the hold-open bounds were still being written into a module-level table as
recently as the rewrite that precedes these tests.

Every failure mode here is invisible with one door configured, which is why
it needs its own file rather than a case tacked onto the single-door tests.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.powerpetdoor.const import DOMAIN

from .conftest import SECOND_HOST, TEST_HOST, TEST_PORT

type TwoDoors = tuple[MockConfigEntry, MagicMock, MockConfigEntry, MagicMock]


async def test_both_doors_set_up_as_separate_devices(
    hass: HomeAssistant, two_doors: TwoDoors
) -> None:
    """Two entries, two devices, two full sets of entities."""
    first_entry, _first, second_entry, _second = two_doors
    assert first_entry.state is ConfigEntryState.LOADED
    assert second_entry.state is ConfigEntryState.LOADED

    devices = dr.async_get(hass)
    assert devices.async_get_device(identifiers={(DOMAIN, f"{TEST_HOST}:{TEST_PORT}")})
    assert devices.async_get_device(identifiers={(DOMAIN, f"{SECOND_HOST}:{TEST_PORT}")})

    entities = er.async_get(hass)
    first = er.async_entries_for_config_entry(entities, first_entry.entry_id)
    second = er.async_entries_for_config_entry(entities, second_entry.entry_id)
    assert len(first) == len(second)
    assert first, "no entities created"

    # No unique_id may appear on both, or Home Assistant would have refused
    # the second entity and one door would silently be missing controls.
    assert not {entry.unique_id for entry in first} & {entry.unique_id for entry in second}


async def test_a_command_reaches_only_the_door_it_was_aimed_at(
    hass: HomeAssistant, two_doors: TwoDoors
) -> None:
    """Acting on one door must not touch the other. This is issue #9."""
    _first_entry, first_door, _second_entry, second_door = two_doors

    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": "switch.power_pet_door_power"},
        blocking=True,
    )

    first_door.set_power.assert_awaited_once_with(False)
    second_door.set_power.assert_not_awaited()


async def test_state_pushed_by_one_door_does_not_move_the_other(
    hass: HomeAssistant, two_doors: TwoDoors
) -> None:
    """A push from one door updates its own entities only.

    The old design registered listeners per entity against a shared client,
    so a settings push moved every door's entities at once - the exact
    symptom reported in issue #9.
    """
    _first_entry, first_door, _second_entry, second_door = two_doors

    assert hass.states.get("switch.power_pet_door_inside_sensor").state == "on"
    assert hass.states.get("switch.back_door_inside_sensor").state == "on"

    first_door.inside_sensor = False
    for callback in first_door._callbacks["on_settings_change"]:
        callback({})
    await hass.async_block_till_done()

    assert hass.states.get("switch.power_pet_door_inside_sensor").state == "off"
    assert hass.states.get("switch.back_door_inside_sensor").state == "on"
    assert second_door.inside_sensor is True


async def test_per_entry_options_do_not_leak_between_doors(
    hass: HomeAssistant, two_doors: TwoDoors
) -> None:
    """Each door's hold-open bounds come from its OWN config entry.

    These used to be assigned into a module-level description table during
    platform setup, so whichever door was set up last decided the bounds for
    both. Invisible with one door; wrong for everyone with two.
    """
    first = hass.states.get("number.power_pet_door_hold_open_time")
    second = hass.states.get("number.back_door_hold_open_time")

    assert (first.attributes["min"], first.attributes["max"], first.attributes["step"]) == (
        2.0,
        8.0,
        2.0,
    )
    assert (second.attributes["min"], second.attributes["max"], second.attributes["step"]) == (
        1.0,
        30.0,
        0.5,
    )


async def test_unloading_one_door_leaves_the_other_running(
    hass: HomeAssistant, two_doors: TwoDoors
) -> None:
    """Removing one door must not disconnect or break the other."""
    first_entry, first_door, second_entry, second_door = two_doors

    assert await hass.config_entries.async_unload(first_entry.entry_id)
    await hass.async_block_till_done()

    assert first_entry.state is ConfigEntryState.NOT_LOADED
    assert second_entry.state is ConfigEntryState.LOADED
    first_door.disconnect.assert_awaited()
    second_door.disconnect.assert_not_awaited()

    # The surviving door is still fully operable.
    assert hass.states.get("switch.back_door_power").state == "on"
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.back_door_power"}, blocking=True
    )
    second_door.set_power.assert_awaited_once_with(False)


async def test_the_websocket_api_resolves_each_door_separately(
    hass: HomeAssistant, two_doors: TwoDoors, hass_ws_client
) -> None:
    """A schedule command must reach the door owning the named entity.

    `_resolve` goes through the entity registry to find the config entry
    behind an entity_id, precisely so this cannot cross doors. With two
    configured, a bug here would silently edit the wrong pet door's
    schedule.
    """
    client = await hass_ws_client(hass)

    await client.send_json_auto_id({"type": f"{DOMAIN}/schedule/list"})
    listed = (await client.receive_json())["result"]
    assert len({entry["entity_id"] for entry in listed}) == len(listed)
    # Two doors x two schedule kinds.
    assert len(listed) == 4

    await client.send_json_auto_id(
        {
            "type": f"{DOMAIN}/schedule/get",
            "entity_id": "binary_sensor.back_door_inside_schedule",
        }
    )
    message = await client.receive_json()
    assert message["success"]
    assert message["result"]["entity_id"] == "binary_sensor.back_door_inside_schedule"
    assert message["result"]["kind"] == "inside"
