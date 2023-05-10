""" Power Pet Door """
from __future__ import annotations

import logging
import datetime
from asyncio import TimeoutError

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from .client import PowerPetDoorClient
from .const import (
    DOMAIN,
    CONF_NAME,
    CONF_HOST,
    CONF_PORT,
    CONF_KEEP_ALIVE,
    CONF_TIMEOUT,
    CONF_UPDATE,
    CONF_RECONNECT,
    CONFIG,
)

PLATFORMS = [ Platform.SENSOR, Platform.COVER, Platform.SWITCH, Platform.BUTTON ]

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Power Pet Door from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    host = entry.data.get(CONF_HOST)
    port = entry.data.get(CONF_PORT)
    name = entry.data.get(CONF_NAME)
    device_id = f"{host}:{port}"

    client = PowerPetDoorClient(
        host=host,
        port=port,
        timeout=entry.options.get(CONF_TIMEOUT, entry.data.get(CONF_TIMEOUT)),
        reconnect=entry.options.get(CONF_RECONNECT, entry.data.get(CONF_RECONNECT)),
        keepalive=entry.options.get(CONF_KEEP_ALIVE, entry.data.get(CONF_KEEP_ALIVE)),
        loop=hass.loop,
    )

    device_info = DeviceInfo(
        identifiers={(DOMAIN, device_id)},
        manufacturer="High Tech Pet",
        model="WiFi Power Pet Door",
        name=name
    )

    hass.data[DOMAIN][device_id] = {
        "client": client,
        "device": device_info,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_update_listener))
    return True


async def async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""

    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Power Pet Door config entry."""

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


