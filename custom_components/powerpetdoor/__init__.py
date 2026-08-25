# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""The Power Pet Door integration."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from powerpetdoor.i18n import get_locale, load_locale

from .coordinator import PowerPetDoorConfigEntry, PowerPetDoorCoordinator
from .migration import async_migrate_legacy_unique_ids
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
    # The library translates its own log messages, and it reads the locale
    # JSON from disk the first time one is needed. Building the door with
    # `loop=` logs "Latching onto an existing event loop", so the very first
    # thing `PowerPetDoorCoordinator.__init__` does is that file read - on
    # the event loop, because `async_setup_entry` runs there. Home Assistant
    # detects it and tells the user to file a bug against this integration.
    #
    # The library caches the table in a module global, so warming it in the
    # executor first leaves the constructor with nothing to read. Idempotent
    # and process-wide: a second door costs nothing.
    await hass.async_add_executor_job(load_locale, get_locale())

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

    # Before the platforms, never after: each one claims its unique_id as it
    # adds entities, so a key renamed afterwards has already lost the race to
    # the duplicate the platform just created.
    async_migrate_legacy_unique_ids(hass, entry)

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
