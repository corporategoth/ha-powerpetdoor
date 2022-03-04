""" Power Pet Door """
from __future__ import annotations

import logging
import asyncio

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
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
    CMD_GET_DOOR_STATUS,
)

PLATFORMS = [ Platform.SENSOR, Platform.SWITCH ]

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Power Pet Door from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    host = entry.data.get(CONF_HOST)
    port = entry.data.get(CONF_PORT)
    name = entry.data.get(CONF_NAME)
    device_id = f"{host}:{port}"

    timeout = entry.data.get(CONF_TIMEOUT)
    client = PowerPetDoorClient(
        host=host,
        port=port,
        keepalive=entry.data.get(CONF_KEEP_ALIVE),
        timeout=timeout,
        reconnect=entry.data.get(CONF_RECONNECT),
        loop=hass.loop,
    )

    device_info = DeviceInfo(
        identifiers={(DOMAIN, device_id)},
        manufacturer="High Tech Pet",
        model="WiFi Power Pet Door",
        name=name
    )

    async def async_update_data() -> str | None:
        future = client.send_message(CONFIG, CMD_GET_DOOR_STATUS, notify=True)
        if future is not None:
            try:
                return await asyncio.wait_for(future, timeout)
            except asyncio.TimeoutError:
                _LOGGER.error("Timed out waiting for status update!")
                return None
        else:
            return None

    coordinator = DataUpdateCoordinator(
        hass=hass,
        logger=_LOGGER,
        name=name,
        update_method=async_update_data,
        update_interval=entry.data.get(CONF_UPDATE)
    )

    hass.data[DOMAIN][device_id] = {
        "client": client,
        "device": device_info,
        "coordinator": coordinator
    }

    hass.config_entries.async_setup_platforms(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_update_listener))
    return True


async def async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""

    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Power Pet Door config entry."""

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


