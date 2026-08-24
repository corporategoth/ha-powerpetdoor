# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""The Power Pet Door integration."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import PowerPetDoorConfigEntry, PowerPetDoorCoordinator
from .websocket import async_register_websocket_api

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.COVER,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: PowerPetDoorConfigEntry) -> bool:
    """Set up Power Pet Door from a config entry."""
    coordinator = PowerPetDoorCoordinator(hass, entry)

    # Connect before anything else so an unreachable door raises
    # ConfigEntryNotReady and Home Assistant retries, rather than creating a
    # device full of unavailable entities (platinum: test-before-setup).
    await coordinator.async_connect()
    entry.async_on_unload(coordinator.async_shutdown)

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    # Registered against hass, not the entry, and therefore only once no
    # matter how many doors are configured. The commands resolve the door
    # from the entity_id in each message.
    async_register_websocket_api(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PowerPetDoorConfigEntry) -> bool:
    """Unload a config entry.

    The connection is closed by the `async_on_unload(coordinator.async_shutdown)`
    registered during setup, which runs after this returns - so there is no
    teardown here beyond the platforms.
    """
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: PowerPetDoorConfigEntry) -> None:
    """Reload when the options change.

    Timeouts, keepalive and the reconnect interval are constructor arguments
    to the library's door object, so there is nothing to mutate in place -
    a reload is the honest way to apply them.
    """
    await hass.config_entries.async_reload(entry.entry_id)
