from __future__ import annotations

import logging
import json
import copy
from datetime import datetime, timezone, timedelta

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.device_registry import async_get as async_get_device_registry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, CoordinatorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.components.sensor import SensorEntity, SensorStateClass, SensorDeviceClass
from .client import PowerPetDoorClient
from homeassistant.const import (
    ATTR_SW_VERSION,
    ATTR_HW_VERSION,
    ATTR_IDENTIFIERS,
    TIME_MILLISECONDS,
    PERCENTAGE,
)

from .const import (
    DOMAIN,
    CONF_HOST,
    CONF_PORT,
    CONF_NAME,
    CONF_REFRESH,
    CONFIG,
    CMD_GET_DOOR_STATUS,
    CMD_GET_SETTINGS,
    CMD_GET_HW_INFO,
    CMD_GET_DOOR_BATTERY,
    STATE_LAST_CHANGE,
    STATE_BATTERY_CHARGING,
    STATE_BATTERY_DISCHARGING,
    FIELD_DOOR_STATUS,
    FIELD_BATTERY_PERCENT,
    FIELD_BATTERY_PRESENT,
    FIELD_AC_PRESENT,
    FIELD_FW_VER,
    FIELD_FW_REV,
    FIELD_FW_MAJOR,
    FIELD_FW_MINOR,
    FIELD_FW_PATCH,
)

_LOGGER = logging.getLogger(__name__)

class PetDoorCoordinator(CoordinatorEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = TIME_MILLISECONDS

    last_change = None
    def __init__(self,
                 hass: HomeAssistant,
                 client: PowerPetDoorClient,
                 name: str,
                 device: DeviceInfo | None = None,
                 update_interval: float | None = None) -> None:
        coordinator = DataUpdateCoordinator(
                hass=hass,
                logger=_LOGGER,
                name=name,
                update_method=self.update_method,
                update_interval=timedelta(seconds=update_interval) if update_interval else None)

        super().__init__(coordinator)
        self.client = client

        self.client.on_connect = self.on_connect
        self.client.on_ping = self.on_ping

        self._attr_name = coordinator.name
        self._attr_device_info = device
        self._attr_unique_id = f"{client.host}:{client.port}"

        self.client.add_listener(name=self.unique_id,
                                 hw_info_update=self.handle_hw_info)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.client.start()
        await self.coordinator.async_refresh()

    async def async_will_remove_from_hass(self) -> None:
        self.client.stop()
        await super().async_will_remove_from_hass()

    @callback
    async def update_method(self) -> dict:
        _LOGGER.debug("Requesting update of door settings")
        future = self.client.send_message(CONFIG, CMD_GET_SETTINGS, notify=True)
        return await future

    @property
    def available(self) -> bool:
        return (self.client.available and super().available)

    @property
    def icon(self) -> str | None:
        if self.client.available:
            if super().available:
                return "mdi:lan-connect"
            else:
                return "mdi:lan-pending"
        else:
            return "mdi:lan-disconnect"

    @property
    def extra_state_attributes(self) -> dict | None:
        rv = copy.deepcopy(self.coordinator.data if self.coordinator.data else {})
        rv[CONF_HOST] = self.client.host
        rv[CONF_PORT] = self.client.port
        if self.coordinator.data:
            rv[FIELD_DOOR_STATUS] = self.coordinator.data
        if ATTR_HW_VERSION in self.device_info:
            rv[ATTR_HW_VERSION] = self.device_info[ATTR_HW_VERSION]
        if ATTR_SW_VERSION in self.device_info:
            rv[ATTR_SW_VERSION] = self.device_info[ATTR_SW_VERSION]
        if self.last_change:
            rv[STATE_LAST_CHANGE] = self.last_change.isoformat()
        return rv

    @callback
    def _handle_coordinator_update(self) -> None:
        self.last_change = datetime.now(timezone.utc)
        super()._handle_coordinator_update()

    def handle_hw_info(self, fwinfo: dict) -> None:
        hw_version = "{0} rev {1}".format(fwinfo[FIELD_FW_VER], fwinfo[FIELD_FW_REV])
        sw_version = "{0}.{1}.{2}".format(fwinfo[FIELD_FW_MAJOR], fwinfo[FIELD_FW_MINOR], fwinfo[FIELD_FW_PATCH])
        self._attr_device_info[ATTR_HW_VERSION] = hw_version
        self._attr_device_info[ATTR_SW_VERSION] = sw_version
        self.async_schedule_update_ha_state()

        registry = async_get_device_registry(self.hass)
        if registry:
            device = registry.async_get_device(identifiers=self.device_info[ATTR_IDENTIFIERS])
            registry.async_update_device(device.id, hw_version=hw_version, sw_version=sw_version)

    def on_connect(self) -> None:
        self.client.send_message(CONFIG, CMD_GET_HW_INFO)

    def on_ping(self, value: int) -> None:
        self._attr_native_value = value
        self.async_schedule_update_ha_state()

class PetDoorBattery(CoordinatorEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    last_change = None
    def __init__(self,
                 hass: HomeAssistant,
                 client: PowerPetDoorClient,
                 name: str,
                 device: DeviceInfo | None = None,
                 update_interval: float | None= None) -> None:
        coordinator = DataUpdateCoordinator(
                hass=hass,
                logger=_LOGGER,
                name=name,
                update_method=self.update_method,
                update_interval=timedelta(seconds=update_interval) if update_interval else None)
        super().__init__(coordinator)

        self.client = client

        self._attr_name = name
        self._attr_device_info = device
        self._attr_unique_id = f"{client.host}:{client.port}-battery"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        await self.coordinator.async_refresh()

    @callback
    async def update_method(self) -> dict:
        _LOGGER.debug("Requesting update of door battery status")
        future = self.client.send_message(CONFIG, CMD_GET_DOOR_BATTERY, notify=True)
        return await future

    @property
    def available(self) -> bool:
        return (self.client.available and super().available and self.battery_present)

    @property
    def icon(self) -> str | None:
        if self.native_value is None:
            return "mdi:battery-unknown"
        elif self.battery_present:
            if self.native_value < 10.0:
                if self.ac_present:
                    return "mdi:battery-charging"
                else:
                    return "mdi:battery-outline"
            if self.native_value < 20.0:
                if self.ac_present:
                    return "mdi:battery-charging-10"
                else:
                    return "mdi:battery-10"
            elif self.native_value < 30.0:
                if self.ac_present:
                    return "mdi:battery-charging-20"
                else:
                    return "mdi:battery-20"
            elif self.native_value < 40.0:
                if self.ac_present:
                    return "mdi:battery-charging-30"
                else:
                    return "mdi:battery-30"
            elif self.native_value < 50.0:
                if self.ac_present:
                    return "mdi:battery-charging-40"
                else:
                    return "mdi:battery-40"
            elif self.native_value < 60.0:
                if self.ac_present:
                    return "mdi:battery-charging-50"
                else:
                    return "mdi:battery-50"
            elif self.native_value < 70.0:
                if self.ac_present:
                    return "mdi:battery-charging-60"
                else:
                    return "mdi:battery-60"
            elif self.native_value < 80.0:
                if self.ac_present:
                    return "mdi:battery-charging-70"
                else:
                    return "mdi:battery-70"
            elif self.native_value < 90.0:
                if self.ac_present:
                    return "mdi:battery-charging-80"
                else:
                    return "mdi:battery-80"
            elif self.native_value < 100.0:
                if self.ac_present:
                    return "mdi:battery-charging-90"
                else:
                    return "mdi:battery-90"
            else:
                return "mdi:battery"
        else:
            return "mdi:battery-off-outline"

    @callback
    def _handle_coordinator_update(self) -> None:
        self.last_change = datetime.now(timezone.utc)
        super()._handle_coordinator_update()

    @property
    def extra_state_attributes(self) -> dict | None:
        rv = {}
        if self.available and self.native_value:
            rv[STATE_BATTERY_DISCHARGING] = not self.ac_present
            if self.native_value < 100.0:
                rv[STATE_BATTERY_CHARGING] = self.ac_present
            else:
                rv[STATE_BATTERY_CHARGING] = False
        if self.last_change:
            rv[STATE_LAST_CHANGE] = self.last_change.isoformat()
        return rv

    @property
    def native_value(self) -> float:
        return self.coordinator.data.get(FIELD_BATTERY_PERCENT) if self.coordinator.data else None

    @property
    def battery_present(self) -> bool:
        return self.coordinator.data.get(FIELD_BATTERY_PRESENT) if self.coordinator.data else None

    @property
    def ac_present(self) -> bool:
        return self.coordinator.data.get(FIELD_AC_PRESENT) if self.coordinator.data else None

# Right now this can be an alias for the above
async def async_setup_entry(hass: HomeAssistant,
                            entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:

    host = entry.data.get(CONF_HOST)
    port = entry.data.get(CONF_PORT)
    name = entry.data.get(CONF_NAME)
    device_id = f"{host}:{port}"

    obj = hass.data[DOMAIN][device_id]

    async_add_entities([
        PetDoorCoordinator(hass=hass,
                           client=obj["client"],
                           name=name,
                           device=obj["device"],
                           update_interval=entry.options.get(CONF_REFRESH, entry.data.get(CONF_REFRESH))),
        PetDoorBattery(hass=hass,
                       client=obj["client"],
                       name=f"{name} - Battery",
                       device=obj["device"],
                       update_interval=entry.options.get(CONF_REFRESH, entry.data.get(CONF_REFRESH))),
    ])
