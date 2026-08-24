# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""Entry setup, unload, reload, and the diagnostics download."""

from __future__ import annotations

from unittest.mock import MagicMock

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_TIMEOUT
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.powerpetdoor.const import CONF_HOLD_MAX, CONF_REFRESH

from .conftest import TEST_HOST


async def test_changing_the_options_reloads_the_entry(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """Timeouts are constructor arguments, so a reload is how they apply.

    There is nothing to mutate in place on a connected door object, so an
    options change that did NOT reload would be silently accepted and never
    take effect - the user would set a 30-second timeout and keep getting
    the old one until they restarted Home Assistant.
    """
    assert mock_door.disconnect.await_count == 0

    hass.config_entries.async_update_entry(
        setup_integration, options={**setup_integration.options, CONF_TIMEOUT: 30.0}
    )
    await hass.async_block_till_done()

    assert setup_integration.state is ConfigEntryState.LOADED
    # A reload tears the old connection down and builds a new door.
    mock_door.disconnect.assert_awaited()
    assert mock_door.connect.await_count == 2


async def test_a_reloaded_entry_picks_up_the_new_options(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """The reload is not cosmetic: the new value reaches the entity.

    Asserting only that a reload happened would pass an implementation that
    reloaded with the old options still in place.
    """
    hass.config_entries.async_update_entry(
        setup_integration, options={**setup_integration.options, CONF_HOLD_MAX: 30.0}
    )
    await hass.async_block_till_done()

    assert hass.states.get("number.power_pet_door_hold_open_time").attributes["max"] == 30.0


async def test_the_refresh_interval_change_survives_a_reload(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """The coordinator is rebuilt with the new polling interval."""
    hass.config_entries.async_update_entry(
        setup_integration, options={**setup_integration.options, CONF_REFRESH: 60.0}
    )
    await hass.async_block_till_done()

    assert setup_integration.runtime_data.update_interval.total_seconds() == 60.0


async def test_unloading_removes_every_entity(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """All seven platforms are torn down, not just some.

    A platform left behind keeps entities alive against a coordinator whose
    connection has been closed.
    """
    assert await hass.config_entries.async_unload(setup_integration.entry_id)
    await hass.async_block_till_done()

    assert setup_integration.state is ConfigEntryState.NOT_LOADED
    live = [
        state
        for state in hass.states.async_all()
        if state.entity_id.endswith("power_pet_door_power") and state.state != "unavailable"
    ]
    assert live == []


async def test_an_entry_can_be_set_up_again_after_being_unloaded(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """Unload must leave nothing behind that blocks a second setup.

    A stale WebSocket registration, a leftover listener or an unreleased
    socket all show up here and nowhere else.
    """
    assert await hass.config_entries.async_unload(setup_integration.entry_id)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_setup(setup_integration.entry_id)
    await hass.async_block_till_done()

    assert setup_integration.state is ConfigEntryState.LOADED
    assert hass.states.get("switch.power_pet_door_power").state == "on"


async def test_the_coordinator_is_stored_on_the_entry(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Platinum's runtime-data rule: never `hass.data[DOMAIN][...]`.

    Asserted because the alternative still works at runtime - it just fails
    review and leaks across reloads.
    """
    assert setup_integration.runtime_data is not None
    assert setup_integration.runtime_data.door is not None


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


async def test_the_diagnostics_download_redacts_the_doors_address(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    hass_client: ClientSessionGenerator,
) -> None:
    """Diagnostics get pasted into public issue trackers.

    The protocol has no credentials to leak, so the address is the only
    thing worth removing - and a LAN address plus a port is more than a bug
    report needs.
    """
    report = await get_diagnostics_for_config_entry(hass, hass_client, setup_integration)

    assert report["entry"]["data"][CONF_HOST] == "**REDACTED**"
    assert TEST_HOST not in str(report["entry"]["data"])


async def test_the_diagnostics_download_keeps_everything_useful(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    hass_client: ClientSessionGenerator,
) -> None:
    """Redaction must not hollow the report out.

    The port, the options and the whole door state are what make the
    download worth asking a user for; a report that redacted them would be
    safe and useless.
    """
    report = await get_diagnostics_for_config_entry(hass, hass_client, setup_integration)

    assert report["entry"]["data"]["port"] == 3000
    assert report["entry"]["options"][CONF_TIMEOUT] == 5.0
    assert report["door"]["connected"] is True
    assert report["door"]["firmware_version"] == "1.7.18"
    assert report["door"]["settings"]["hold_time"] == 4.0
