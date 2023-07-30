from __future__ import annotations

from datetime import datetime, timezone, timedelta
import copy

from homeassistant.core import HomeAssistant, callback
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity import DeviceInfo, Entity, ToggleEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry, SOURCE_IMPORT
from homeassistant.components.switch import SwitchDeviceClass
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, CoordinatorEntity
from .client import PowerPetDoorClient, make_bool

from .const import (
    DOMAIN,
    CONF_HOST,
    CONF_PORT,
    CONF_NAME,
    CONF_REFRESH,
    CONFIG,
    CMD_GET_SENSORS,
    CMD_GET_POWER,
    CMD_GET_AUTO,
    CMD_GET_OUTSIDE_SENSOR_SAFETY_LOCK,
    CMD_GET_CMD_LOCKOUT,
    CMD_GET_AUTORETRACT,
    CMD_GET_NOTIFICATIONS,
    CMD_SET_NOTIFICATIONS,
    CMD_ENABLE_INSIDE,
    CMD_DISABLE_INSIDE,
    CMD_ENABLE_OUTSIDE,
    CMD_DISABLE_OUTSIDE,
    CMD_POWER_ON,
    CMD_POWER_OFF,
    CMD_ENABLE_AUTO,
    CMD_DISABLE_AUTO,
    CMD_DISABLE_OUTSIDE_SENSOR_SAFETY_LOCK,
    CMD_ENABLE_OUTSIDE_SENSOR_SAFETY_LOCK,
    CMD_DISABLE_CMD_LOCKOUT,
    CMD_ENABLE_CMD_LOCKOUT,
    CMD_DISABLE_AUTORETRACT,
    CMD_ENABLE_AUTORETRACT,
    STATE_LAST_CHANGE,
    FIELD_INSIDE,
    FIELD_OUTSIDE,
    FIELD_POWER,
    FIELD_AUTO,
    FIELD_OUTSIDE_SENSOR_SAFETY_LOCK,
    FIELD_CMD_LOCKOUT,
    FIELD_AUTORETRACT,
    FIELD_SENSOR_ON_INDOOR_NOTIFICATIONS,
    FIELD_SENSOR_OFF_INDOOR_NOTIFICATIONS,
    FIELD_SENSOR_ON_OUTDOOR_NOTIFICATIONS,
    FIELD_SENSOR_OFF_OUTDOOR_NOTIFICATIONS,
    FIELD_LOW_BATTERY_NOTIFICATIONS,
)

import logging

_LOGGER = logging.getLogger(__name__)

SWITCHES = {
    "inside": {
        "field": FIELD_INSIDE,
        "update": CMD_GET_SENSORS,
        "enable": CMD_ENABLE_INSIDE,
        "disable": CMD_DISABLE_INSIDE,
        "icon_on": "mdi:leak",
        "icon_off": "mdi:leak-off",
        "category": EntityCategory.CONFIG
    },
    "outside": {
        "field": FIELD_OUTSIDE,
        "update": CMD_GET_SENSORS,
        "enable": CMD_ENABLE_OUTSIDE,
        "disable": CMD_DISABLE_OUTSIDE,
        "icon_on": "mdi:leak",
        "icon_off": "mdi:leak-off",
        "category": EntityCategory.CONFIG
    },
    "auto": {
        "field": FIELD_AUTO,
        "update": CMD_GET_AUTO,
        "enable": CMD_ENABLE_AUTO,
        "disable": CMD_DISABLE_AUTO,
        "icon_on": "mdi:calendar-week",
        "icon_off": "mdi:calendar-remove",
        "category": EntityCategory.CONFIG
    },
    "outside_sensor_safety_lock": {
        "field": FIELD_OUTSIDE_SENSOR_SAFETY_LOCK,
        "update": CMD_GET_OUTSIDE_SENSOR_SAFETY_LOCK,
        "enable": CMD_ENABLE_OUTSIDE_SENSOR_SAFETY_LOCK,
        "disable": CMD_DISABLE_OUTSIDE_SENSOR_SAFETY_LOCK,
        "icon_on": "mdi:weather-sunny-alert",
        "icon_off": "mdi:shield-sun-outline",
        "category": EntityCategory.CONFIG,
        "disabled": True,
    },
    "cmd_lockout": {
        "field": FIELD_CMD_LOCKOUT,
        "update": CMD_GET_CMD_LOCKOUT,
        "enable": CMD_ENABLE_CMD_LOCKOUT,
        "disable": CMD_DISABLE_CMD_LOCKOUT,
        "icon_on": "mdi:window-shutter-open",
        "icon_off": "mdi:window-shutter",
        "category": EntityCategory.CONFIG,
        "inverted": True,
        "disabled": True,
    },
    "autoretract": {
        "field": FIELD_AUTORETRACT,
        "update": CMD_GET_AUTORETRACT,
        "enable": CMD_ENABLE_AUTORETRACT,
        "disable": CMD_DISABLE_AUTORETRACT,
        "icon_on": "mdi:window-shutter-alert",
        "icon_off": "mdi:window-shutter-settings",
        "category": EntityCategory.CONFIG,
        "disabled": True,
    },
    "power": {
        "field": FIELD_POWER,
        "update": CMD_GET_POWER,
        "enable": CMD_POWER_ON,
        "disable": CMD_POWER_OFF,
        "icon_on": "mdi:power",
        "icon_off": "mdi:power-off"
    },
}

NOTIFICATION_SWITCHES = {
    "inside_on": {
        "field": FIELD_SENSOR_ON_INDOOR_NOTIFICATIONS,
        "icon_on": "mdi:motion-sensor",
        "icon_off": "mdi:motion-sensor-off",
        "disabled": True,
    },
    "inside_off": {
        "field": FIELD_SENSOR_OFF_INDOOR_NOTIFICATIONS,
        "icon_on": "mdi:motion-sensor",
        "icon_off": "mdi:motion-sensor-off",
        "disabled": True,
    },
    "outside_on": {
        "field": FIELD_SENSOR_ON_OUTDOOR_NOTIFICATIONS,
        "icon_on": "mdi:motion-sensor",
        "icon_off": "mdi:motion-sensor-off",
        "disabled": True,
    },
    "outside_off": {
        "field": FIELD_SENSOR_OFF_OUTDOOR_NOTIFICATIONS,
        "icon_on": "mdi:motion-sensor",
        "icon_off": "mdi:motion-sensor-off",
        "disabled": True,
    },
    "low_battery": {
        "field": FIELD_LOW_BATTERY_NOTIFICATIONS,
        "icon_on": "mdi:battery-alert-variant-outline",
        "icon_off": "mdi:battery-remove-outline",
        "disabled": True,
    },
}

class PetDoorSwitch(CoordinatorEntity, ToggleEntity):
    _attr_device_class = SwitchDeviceClass.SWITCH
    last_change = None
    power = True

    def __init__(self,
                 client: PowerPetDoorClient,
                 name: str,
                 switch: dict,
                 coordinator: DataUpdateCoordinator,
                 device: DeviceInfo | None = None) -> None:
        super().__init__(coordinator)
        self.client = client
        self.switch = switch

        self._attr_name = name
        self._attr_entity_category = switch.get("category")
        self._attr_entity_registry_enabled_default = not switch.get("disabled", False)
        self._attr_device_info = device
        self._attr_unique_id = f"{client.host}:{client.port}-{switch['field']}"

        client.add_listener(name=self.unique_id, sensor_update={switch["field"]: self.handle_state_update})
        if switch["field"] is not FIELD_POWER:
            client.add_listener(name=self.unique_id, sensor_update={FIELD_POWER: self.handle_power_update})

    @property
    def available(self) -> bool:
        return self.client.available and super().available and self.power

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
        if self.coordinator.data and state != self.coordinator.data[self.switch["field"]]:
            changed = self.coordinator.data
            changed[self.switch["field"]] = state
            self.coordinator.async_set_updated_data(changed)

    @callback
    def _handle_coordinator_update(self) -> None:
        self.last_change = datetime.now(timezone.utc)
        if self.coordinator.data:
            if self.switch["field"] is not FIELD_POWER and FIELD_POWER in self.coordinator.data:
                self.power = self.coordinator.data[FIELD_POWER]
        super()._handle_coordinator_update()

    @callback
    def handle_power_update(self, state: bool) -> None:
        self.power = state
        if self.enabled:
            self.async_schedule_update_ha_state()

    @property
    def is_on(self) -> bool:
        if self.coordinator.data is None:
            return None
        if self.switch.get("inverted", False):
            return not make_bool(self.coordinator.data[self.switch["field"]])
        else:
            return make_bool(self.coordinator.data[self.switch["field"]])

    async def async_turn_on(self) -> None:
        """Turn the entity on."""
        if self.switch.get("inverted", False):
            self.client.send_message(CONFIG, self.switch["disable"])
        else:
            self.client.send_message(CONFIG, self.switch["enable"])

    async def async_turn_off(self) -> None:
        """Turn the entity off."""
        if self.switch.get("inverted", False):
            self.client.send_message(CONFIG, self.switch["enable"])
        else:
            self.client.send_message(CONFIG, self.switch["disable"])

class PetDoorNotificationSwitch(CoordinatorEntity, ToggleEntity):
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_entity_category = EntityCategory.CONFIG
    last_change = None
    power = True

    def __init__(self,
                 client: PowerPetDoorClient,
                 name: str,
                 switch: dict,
                 coordinator: DataUpdateCoordinator,
                 device: DeviceInfo | None = None) -> None:
        super().__init__(coordinator)
        self.client = client
        self.switch = switch

        self._attr_name = name
        if "disabled" in switch:
            self._attr_entity_registry_enabled_default = not switch["disabled"]
        self._attr_device_info = device
        self._attr_unique_id = f"{client.host}:{client.port}-{switch['field']}"

        client.add_listener(name=self.unique_id,
                            notifications_update={switch["field"]: self.handle_state_update},
                            sensor_update={FIELD_POWER: self.handle_power_update})

    @property
    def available(self) -> bool:
        return self.client.available and super().available and self.power

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
        if self.coordinator.data and state != self.coordinator.data[self.switch["field"]]:
            changed = self.coordinator.data
            changed[self.switch["field"]] = make_bool(state)
            self.coordinator.async_set_updated_data(changed)

    @callback
    def _handle_coordinator_update(self) -> None:
        self.last_change = datetime.now(timezone.utc)
        super()._handle_coordinator_update()

    @callback
    def handle_power_update(self, state: bool) -> None:
        self.power = state
        if self.enabled:
            self.async_schedule_update_ha_state()

    @property
    def is_on(self) -> bool:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data[self.switch["field"]]

    async def async_turn_on(self) -> None:
        """Turn the entity on."""
        changed = copy.deepcopy(self.coordinator.data)
        changed[self.switch["field"]] = True
        self.client.send_message(CONFIG, CMD_SET_NOTIFICATIONS, notifications=changed)

    async def async_turn_off(self) -> None:
        """Turn the entity off."""
        changed = copy.deepcopy(self.coordinator.data)
        changed[self.switch["field"]] = False
        self.client.send_message(CONFIG, CMD_SET_NOTIFICATIONS, notifications=changed)


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
                      name=f"{name} Inside Sensor",
                      switch=SWITCHES["inside"],
                      coordinator=obj["settings"],
                      device=obj["device"]),
        PetDoorSwitch(client=obj["client"],
                      name=f"{name} Outside Sensor",
                      switch=SWITCHES["outside"],
                      coordinator=obj["settings"],
                      device=obj["device"]),
        PetDoorSwitch(client=obj["client"],
                      name=f"{name} Power",
                      switch=SWITCHES["power"],
                      coordinator=obj["settings"],
                      device=obj["device"]),
        PetDoorSwitch(client=obj["client"],
                      name=f"{name} Auto",
                      switch=SWITCHES["auto"],
                      coordinator=obj["settings"],
                      device=obj["device"]),
        PetDoorSwitch(client=obj["client"],
                      name=f"{name} Outside Safety Lock",
                      switch=SWITCHES["outside_sensor_safety_lock"],
                      coordinator=obj["settings"],
                      device=obj["device"]),
        PetDoorSwitch(client=obj["client"],
                      name=f"{name} Pet Proximity Keep Open",
                      switch=SWITCHES["cmd_lockout"],
                      coordinator=obj["settings"],
                      device=obj["device"]),
        PetDoorSwitch(client=obj["client"],
                      name=f"{name} Auto Retract",
                      switch=SWITCHES["autoretract"],
                      coordinator=obj["settings"],
                      device=obj["device"]),
    ])

    async def update_notifications() -> dict:
        _LOGGER.debug("Requesting update of notifications")
        future = obj["client"].send_message(CONFIG, CMD_GET_NOTIFICATIONS, notify=True)
        result = await future
        for key in result.keys():
            result[key] = make_bool(result[key])
        return result

    notifications_coordinator = DataUpdateCoordinator(
        hass=hass,
        logger=_LOGGER,
        name=f"{name} Notifications",
        update_method=update_notifications,
        update_interval=timedelta(entry.options.get(CONF_REFRESH)))

    obj["client"].add_handlers(f"{name} Notifications", on_connect=notifications_coordinator.async_request_refresh)

    async_add_entities([
        PetDoorNotificationSwitch(client=obj["client"],
                                  name=f"{name} Notify Inside On",
                                  switch=NOTIFICATION_SWITCHES["inside_on"],
                                  coordinator=notifications_coordinator,
                                  device=obj["device"]),
        PetDoorNotificationSwitch(client=obj["client"],
                                  name=f"{name} Notify Inside Off",
                                  switch=NOTIFICATION_SWITCHES["inside_off"],
                                  coordinator=notifications_coordinator,
                                  device=obj["device"]),
        PetDoorNotificationSwitch(client=obj["client"],
                                  name=f"{name} Notify Outside On",
                                  switch=NOTIFICATION_SWITCHES["outside_on"],
                                  coordinator=notifications_coordinator,
                                  device=obj["device"]),
        PetDoorNotificationSwitch(client=obj["client"],
                                  name=f"{name} Notify Outside Off",
                                  switch=NOTIFICATION_SWITCHES["outside_off"],
                                  coordinator=notifications_coordinator,
                                  device=obj["device"]),
        PetDoorNotificationSwitch(client=obj["client"],
                                  name=f"{name} Notify Low Battery",
                                  switch=NOTIFICATION_SWITCHES["low_battery"],
                                  coordinator=notifications_coordinator,
                                  device=obj["device"]),
    ])
