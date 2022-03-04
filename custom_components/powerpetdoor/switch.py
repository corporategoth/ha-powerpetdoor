from __future__ import annotations

import voluptuous as vol
from datetime import datetime, timezone

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import Entity, ToggleEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry, SOURCE_IMPORT
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.switch import SwitchDeviceClass
from homeassistant.helpers import entity_platform
from homeassistant.const import STATE_ON, STATE_OFF
import homeassistant.helpers.config_validation as cv
from .client import PowerPetDoorClient

from .const import (
    DOMAIN,
    CONF_HOST,
    CONF_PORT,
    CONF_NAME,
    CONF_HOLD,
    ATTR_HOLD,
    PP_SCHEMA,
    PP_SCHEMA_ADV,
    COMMAND,
    CONFIG,
    DOOR_STATE_IDLE,
    DOOR_STATE_CLOSED,
    DOOR_STATE_HOLDING,
    DOOR_STATE_RISING,
    CMD_GET_DOOR_STATUS,
    CMD_GET_SENSORS,
    CMD_GET_POWER,
    CMD_GET_AUTO,
    CMD_ENABLE_INSIDE,
    CMD_DISABLE_INSIDE,
    CMD_ENABLE_OUTSIDE,
    CMD_DISABLE_OUTSIDE,
    CMD_POWER_ON,
    CMD_POWER_OFF,
    CMD_ENABLE_AUTO,
    CMD_DISABLE_AUTO,
    CMD_OPEN,
    CMD_OPEN_AND_HOLD,
    CMD_CLOSE,
    FIELD_INSIDE,
    FIELD_OUTSIDE,
    FIELD_POWER,
    FIELD_AUTO,
    SERVICE_OPEN,
    SERVICE_CLOSE,
    SERVICE_TOGGLE,
)


import logging

_LOGGER = logging.getLogger(__name__)

SWITCHES = {
    "inside": {
        "field": FIELD_INSIDE,
        "update": CMD_GET_SENSORS,
        "enable": CMD_ENABLE_INSIDE,
        "disable": CMD_DISABLE_INSIDE,
        "icon_on": "motion-sensor",
        "icon_off": "motion-sensor-off"
    },
    "outside": {
        "field": FIELD_OUTSIDE,
        "update": CMD_GET_SENSORS,
        "enable": CMD_ENABLE_OUTSIDE,
        "disable": CMD_DISABLE_OUTSIDE,
        "icon_on": "motion-sensor",
        "icon_off": "motion-sensor-off"
    },
    "power": {
        "field": FIELD_POWER,
        "update": CMD_GET_POWER,
        "enable": CMD_POWER_ON,
        "disable": CMD_POWER_OFF,
        "icon_on": "power",
        "icon_off": "power-off"
    },
    "auto": {
        "field": FIELD_AUTO,
        "update": CMD_GET_AUTO,
        "enable": CMD_ENABLE_AUTO,
        "disable": CMD_DISABLE_AUTO,
        "icon_on": "autorenew",
        "icon_off": "autorenew-off"
    },
}

PLATFORM_SCHEMA = cv.PLATFORM_SCHEMA.extend(PP_SCHEMA).extend(PP_SCHEMA_ADV)

DOOR_SCHEMA = {
    vol.Optional(ATTR_HOLD): cv.boolean
}

class PetDoor(Entity):
    _attr_device_class = BinarySensorDeviceClass.DOOR
    _attr_should_poll = False

    last_change = None

    def __init__(self,
                 client: PowerPetDoorClient,
                 name: str,
                 device: DeviceInfo | None = None,
                 hold: bool = True) -> None:
        self.client = client
        self.hold = hold

        self._attr_name = name
        self._attr_device_info = device
        self._attr_unique_id = f"{client.host}:{client.port}-door"

        client.add_listener(name=self.unique_id, door_status_update=self.handle_state_update)

    @callback
    async def async_update(self) -> None:
        _LOGGER.debug("Requesting update of door status")
        self.client.send_message(CONFIG, CMD_GET_DOOR_STATUS)

    @property
    def available(self) -> bool:
        return self.client.available

    @property
    def is_on(self) -> bool | None:
        """Return True if entity is on."""
        return (self._attr_state not in (DOOR_STATE_IDLE, DOOR_STATE_CLOSED))

    @property
    def icon(self) -> str | None:
        if self.is_on:
            return "mdi:dog-side"
        else:
            return "mdi:dog-side-off"

    @property
    def extra_state_attributes(self) -> dict | None:
        rv = { hold: self.hold }
        if self.last_change:
            data["last_change"] = self.last_change.isoformat()

    @property
    async def handle_state_update(self, state: str):
        if self._attr_state is not None and self._attr_state != state:
            self.last_change = datetime.now(timezone.utc)
        self._attr_state = state

    @callback
    async def turn_on(self, hold: bool | None = None, **kwargs: Any) -> None:
        """Turn the entity on."""
        return asyncio.run_coroutine_threadsafe(self.async_turn_on(hold, **kwargs)).result()

    @callback
    async def async_turn_on(self, hold: bool | None = None, **kwargs: Any) -> None:
        """Turn the entity on."""
        if hold is None:
            hold = self.hold
        if hold:
            self.client.send_message(COMMAND, CMD_OPEN_AND_HOLD)
        else:
            self.client.send_message(COMMAND, CMD_OPEN)

    @callback
    async def turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        return asyncio.run_coroutine_threadsafe(self.async_turn_off(**kwargs)).result()

    @callback
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        self.client.send_message(COMMAND, CMD_CLOSE)

    def toggle(self, **kwargs: Any) -> None:
        """Toggle the entity."""
        if self.is_on:
            self.turn_off(**kwargs)
        else:
            self.turn_on(**kwargs)

    async def async_toggle(self, **kwargs: Any) -> None:
        """Toggle the entity."""
        if self.is_on:
            await self.async_turn_off(**kwargs)
        else:
            await self.async_turn_on(**kwargs)


class PetDoorSwitch(ToggleEntity):
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_should_poll = False

    last_change = None

    def __init__(self,
                 client: PowerPetDoorClient,
                 name: str,
                 switch: dict,
                 device: DeviceInfo | None = None) -> None:
        self.client = client
        self.switch = switch

        self._attr_name = name
        self._attr_device_info = device
        self._attr_unique_id = f"{client.host}:{client.port}-{switch['field']}"

        client.add_listener(name=self.unique_id, sensor_update={self.switch["field"]: self.handle_state_update} )

    @callback
    async def async_update(self) -> None:
        _LOGGER.debug("Requesting update of door status")
        self.client.send_message(CONFIG, self.switch["update"])

    @property
    def available(self) -> bool:
        return self.client.available

    @property
    def icon(self) -> str | None:
        if self.is_on:
            return self.switch["icon_on"]
        else:
            return self.switch["icon_off"]

    @property
    def extra_state_attributes(self) -> dict | None:
        rv = { hold: self.hold }
        if self.last_change:
            data["last_change"] = self.last_change.isoformat()

    @property
    async def handle_state_update(self, state: bool):
        state = STATE_ON if state else STATE_OFF
        if self._attr_state is not None and self._attr_state != state:
            self.last_change = datetime.now(timezone.utc)
        self._attr_state = state

    @callback
    async def turn_on(self, hold: bool | None = None, **kwargs: Any) -> None:
        """Turn the entity on."""
        return asyncio.run_coroutine_threadsafe(self.async_turn_on(hold, **kwargs)).result()

    @callback
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        self.client.send_message(COMMAND, self.switch["enable"])

    @callback
    async def turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        return asyncio.run_coroutine_threadsafe(self.async_turn_off(**kwargs)).result()

    @callback
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        self.client.send_message(COMMAND, self.switch["disable"])

async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_devices: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the DNS IP sensor."""
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

# Right now this can be an alias for the above
async def async_setup_entry(hass: HomeAssistant,
                            entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:

    host = entry.data.get(CONF_HOST)
    port = entry.data.get(CONF_PORT)
    name = entry.data.get(CONF_NAME)
    obj = hass.data[DOMAIN][f"{host}:{port}"]

    async_add_entities([
        PetDoor(client=obj["client"],
                name=f"{name}",
                device=obj["device"],
                hold=entry.data.get(CONF_HOLD)),
        PetDoorSwitch(client=obj["client"],
                      name=f"{name} - Inside Sensor",
                      switch=SWITCHES["inside"],
                      device=obj["device"]),
        PetDoorSwitch(client=obj["client"],
                      name=f"{name} - Outside Sensor",
                      switch=SWITCHES["outside"],
                      device=obj["device"]),
        PetDoorSwitch(client=obj["client"],
                      name=f"{name} - Power",
                      switch=SWITCHES["power"],
                      device=obj["device"]),
        PetDoorSwitch(client=obj["client"],
                      name=f"{name} - Auto",
                      switch=SWITCHES["auto"],
                      device=obj["device"]),
    ])

    # These only really apply to the PetDoor
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(SERVICE_CLOSE, {}, "async_turn_off")
    platform.async_register_entity_service(SERVICE_OPEN, DOOR_SCHEMA, "async_turn_on")
    platform.async_register_entity_service(SERVICE_TOGGLE, DOOR_SCHEMA, "async_toggle")
