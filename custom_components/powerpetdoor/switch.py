from __future__ import annotations

from datetime import datetime, timezone, timedelta

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import Entity, ToggleEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry, SOURCE_IMPORT
from homeassistant.components.switch import SwitchDeviceClass
from .client import PowerPetDoorClient

from .const import (
    DOMAIN,
    CONF_HOST,
    CONF_PORT,
    CONF_NAME,
    CONFIG,
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
    STATE_LAST_CHANGE,
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
        "icon_on": "mdi:motion-sensor",
        "icon_off": "mdi:motion-sensor-off"
    },
    "outside": {
        "field": FIELD_OUTSIDE,
        "update": CMD_GET_SENSORS,
        "enable": CMD_ENABLE_OUTSIDE,
        "disable": CMD_DISABLE_OUTSIDE,
        "icon_on": "mdi:motion-sensor",
        "icon_off": "mdi:motion-sensor-off"
    },
    "power": {
        "field": FIELD_POWER,
        "update": CMD_GET_POWER,
        "enable": CMD_POWER_ON,
        "disable": CMD_POWER_OFF,
        "icon_on": "mdi:power",
        "icon_off": "mdi:power-off"
    },
    "auto": {
        "field": FIELD_AUTO,
        "update": CMD_GET_AUTO,
        "enable": CMD_ENABLE_AUTO,
        "disable": CMD_DISABLE_AUTO,
        "icon_on": "mdi:calendar-week",
        "icon_off": "mdi:calendar-remove"
    },
}

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
        if self.last_change:
            return { STATE_LAST_CHANGE: self.last_change.isoformat() }
        return None

    def handle_state_update(self, state: bool) -> None:
        if self._attr_is_on is not None and self._attr_is_on != state:
            self.last_change = datetime.now(timezone.utc)
        self._attr_is_on = state
        self.async_schedule_update_ha_state()

    async def turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        return self.client.run_coroutine_threadsafe(self.async_turn_on(**kwargs)).result()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        self.client.send_message(CONFIG, self.switch["enable"])

    async def turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        return self.client.run_coroutine_threadsafe(self.async_turn_off(**kwargs)).result()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        self.client.send_message(CONFIG, self.switch["disable"])

# Right now this can be an alias for the above
async def async_setup_entry(hass: HomeAssistant,
                            entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:

    host = entry.data.get(CONF_HOST)
    port = entry.data.get(CONF_PORT)
    name = entry.data.get(CONF_NAME)
    obj = hass.data[DOMAIN][f"{host}:{port}"]

    async_add_entities([
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