""" Power Pet Door """
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.config_entries import ConfigEntry, SOURCE_IMPORT
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.const import Platform
from .client import PowerPetDoorClient
from .const import (
    DOMAIN,
    CONF_NAME,
    CONF_HOST,
    CONF_PORT,
    CONF_KEEP_ALIVE,
    CONF_TIMEOUT,
    CONF_REFRESH,
    CONF_UPDATE,
    CONF_RECONNECT,
    CONFIG,
    CMD_GET_SETTINGS,
    CMD_GET_NOTIFICATIONS,
)

PLATFORMS = [ Platform.SENSOR, Platform.COVER, Platform.SWITCH, Platform.BUTTON, Platform.NUMBER ]

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

    async def update_settings() -> dict:
        _LOGGER.debug("Requesting update of settings")
        future = client.send_message(CONFIG, CMD_GET_SETTINGS, notify=True)
        return await future

    settings_coordinator = DataUpdateCoordinator(
        hass=hass,
        logger=_LOGGER,
        name=f"{name} Settings",
        update_method=update_settings,
        update_interval=timedelta(entry.options.get(CONF_REFRESH, entry.data.get(CONF_REFRESH))))

    client.add_handlers(f"{name} Settings", on_connect=settings_coordinator.async_request_refresh)

    hass.data[DOMAIN][device_id] = {
        "client": client,
        "device": device_info,
        "settings": settings_coordinator,
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

async def async_setup_platform(
        hass: HomeAssistant,
        config: ConfigType,
        async_add_devices: AddEntitiesCallback,
        discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the Power Pet Door sensor."""
    _LOGGER.warning(
        "Configuration of the Power Pet Door platform in YAML is deprecated and "
        "will be removed in Home Assistant 2022.6; Your existing configuration "
        "has been imported into the UI automatically and can be safely removed "
        "from your configuration.yaml file"
    )

    hass.async_create_task(
        hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_IMPORT},
            data=config,
        )
    )

