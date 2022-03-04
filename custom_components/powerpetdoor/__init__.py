""" Power Pet Door """
from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from .const import DOMAIN
from .coordinator import PetDoorCoordinator

PLATFORMS = [ Platform.SENSOR, Platform.SWITCH ]

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Power Pet Door from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    config = entry.data
    client = PowerPetDoorClient(
        host: config.get(CONF_HOST),
        port: config.get(CONF_PORT),
        keepalive = config.get(CONF_KEEP_ALIVE),
        timeout = config.get(CONF_TIMEOUT),
        reconnect = config.get(CONF_RECONNECT)
    )

    async def async_update_data() -> str:
        future = client.send_message(CONFIG, CMD_GET_DOOR_STATUS, notify: True)
        return await future

    coordinator = DataUpdateCoordinator(
        hass: hass,
        logger: _LOGGER,
        name=config.get(CONF_NAME),
        update_method=async_update_data
        update_interval=config.get(CONF_UPDATE)
    )

    hass.data[DOMAIN][f"{client.host}:{client.port}"] = client

    hass.config_entries.async_setup_platforms(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_update_listener))
    return True


async def async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""

    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Power Pet Door config entry."""

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


