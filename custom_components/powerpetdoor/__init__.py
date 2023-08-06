""" Power Pet Door """
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant import loader
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.config_entries import ConfigEntry, SOURCE_IMPORT
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.entity_component import EntityComponent
from homeassistant.const import Platform
from homeassistant.components.schedule import Schedule, DOMAIN as SCHEDULE_DOMAIN, LOGGER as SCHEDULE_LOGGER
import homeassistant.helpers.config_validation as cv
from .schema import PP_SCHEMA, PP_OPT_SCHEMA, PP_SCHEMA_ADV, get_validating_schema
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

PLATFORMS = [ Platform.SENSOR, Platform.COVER, Platform.SWITCH, Platform.BUTTON, Platform.NUMBER, SCHEDULE_DOMAIN ]
PLATFORM_SCHEMA = cv.PLATFORM_SCHEMA.extend(get_validating_schema(PP_SCHEMA)).extend(get_validating_schema(PP_OPT_SCHEMA)).extend(get_validating_schema(PP_SCHEMA_ADV))

_LOGGER = logging.getLogger(__name__)

async def schedule_async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Setup a config entry."""
    component: EntityComponent[Schedule] = hass.data[SCHEDULE_DOMAIN]
    return await component.async_setup_entry(entry)

async def schedule_async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Setup a config entry."""
    component: EntityComponent[Schedule] = hass.data[SCHEDULE_DOMAIN]
    return await component.async_unload_entry(entry)

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    hass.data.setdefault(DOMAIN, {})

    # Schedule doesn't set itself up as an entity type for use
    # by other integrations.  This hacks around that so that
    # we can use it as an entity type.
    if not SCHEDULE_DOMAIN in hass.data:
        schedule_component = hass.data[SCHEDULE_DOMAIN] = EntityComponent[Schedule](SCHEDULE_LOGGER, SCHEDULE_DOMAIN, hass)
        await schedule_component.async_setup({})

    integration = await loader.async_get_integration(hass, SCHEDULE_DOMAIN)
    if integration:
        schedule_component = integration.get_component()
        if schedule_component:
            if not hasattr(schedule_component, "async_setup_entry"):
                schedule_component.async_setup_entry = schedule_async_setup_entry
            if not hasattr(schedule_component, "async_unload_entry"):
                schedule_component.async_unload_entry = schedule_async_unload_entry

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Power Pet Door from a config entry."""

    # Make sure everything is populated, with defaults if necessary.
    data = dict(entry.data)
    options = dict(entry.options)
    for ent in PP_OPT_SCHEMA:
        if ent["field"] in data:
            options[ent["field"]] = data[ent["field"]]
            del data[ent["field"]]
        if ent["field"] not in options:
            options[ent["field"]] = ent.get("default")

    for schema in (PP_SCHEMA, PP_SCHEMA_ADV):
        for ent in schema:
            if ent["field"] not in data:
                data[ent["field"]] = ent.get("default")

    if data != entry.data or options != entry.options:
        await entry.async_update_entry(entry, data=data, options=options)

    name = entry.data.get(CONF_NAME)
    host = entry.data.get(CONF_HOST)
    port = entry.data.get(CONF_PORT)
    device_id = f"{host}:{port}"

    client = PowerPetDoorClient(
        host=host,
        port=port,
        timeout=entry.options.get(CONF_TIMEOUT),
        reconnect=entry.options.get(CONF_RECONNECT),
        keepalive=entry.options.get(CONF_KEEP_ALIVE),
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
        update_interval=timedelta(entry.options.get(CONF_REFRESH)))

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

