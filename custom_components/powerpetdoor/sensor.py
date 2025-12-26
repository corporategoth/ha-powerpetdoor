# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""Sensor entities for Power Pet Door."""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from homeassistant.core import HomeAssistant, callback
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.device_registry import async_get as async_get_device_registry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, CoordinatorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.components.sensor import SensorEntity, SensorStateClass, SensorDeviceClass
from powerpetdoor import PowerPetDoorClient
from homeassistant.const import (
    UnitOfTime,
    ATTR_SW_VERSION,
    ATTR_HW_VERSION,
    ATTR_IDENTIFIERS,
    PERCENTAGE,
)

from .const import (
    DOMAIN,
    CONF_HOST,
    CONF_PORT,
    CONF_NAME,
    CONF_UPDATE,
    CONF_REFRESH,
    CONFIG,
    CMD_GET_HW_INFO,
    CMD_GET_DOOR_BATTERY,
    CMD_GET_DOOR_OPEN_STATS,
    STATE_LAST_CHANGE,
    STATE_BATTERY_CHARGING,
    STATE_BATTERY_DISCHARGING,
    FIELD_BATTERY_PERCENT,
    FIELD_BATTERY_PRESENT,
    FIELD_AC_PRESENT,
    FIELD_POWER,
    FIELD_TOTAL_OPEN_CYCLES,
    FIELD_TOTAL_AUTO_RETRACTS,
    FIELD_FW_VER,
    FIELD_FW_REV,
    FIELD_FW_MAJOR,
    FIELD_FW_MINOR,
    FIELD_FW_PATCH,
)

_LOGGER = logging.getLogger(__name__)

STATS = {
    "open_cycles": {
        "field": FIELD_TOTAL_OPEN_CYCLES,
        "icon": "mdi:reload",
        "class": "total_increasing",
        "category": EntityCategory.DIAGNOSTIC,
        "disabled": True,
    },
    "auto_retracts": {
        "field": FIELD_TOTAL_AUTO_RETRACTS,
        "icon": "mdi:alert",
        "class": "total_increasing",
        "category": EntityCategory.DIAGNOSTIC,
        "disabled": True,
    },
}

class PetDoorLatency(CoordinatorEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTime.MILLISECONDS

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

        self._attr_name = name
        self._attr_device_info = device
        self._attr_unique_id = f"{client.host}:{client.port}-latency"

        self.client.add_listener(self.unique_id, hw_info_update=self.handle_hw_info)
        self.client.add_handlers(name, on_connect=self.coordinator.async_request_refresh, on_ping=self.on_ping)

    # NOTE: Lifecycle control (start/stop) is now handled by ConnectionSwitch.
    # The latency sensor is just an observer - disabling it will NOT break the connection.

    @callback
    async def update_method(self) -> dict:
        _LOGGER.debug("Requesting update of firmware status")
        future = self.client.send_message(CONFIG, CMD_GET_HW_INFO, notify=True)
        return await future

    @property
    def available(self) -> bool:
        return self.client.available and super().available

    @property
    def icon(self) -> str | None:
        if self.client.available:
            if super().available:
                return "mdi:lan-connect"
            else:
                return "mdi:lan-pending"
        else:
            return "mdi:lan-disconnect"

    @callback
    def _handle_coordinator_update(self) -> None:
        self.last_change = datetime.now(timezone.utc)

        if self.coordinator.data:
            hw_version = "{0} rev {1}".format(self.coordinator.data[FIELD_FW_VER], self.coordinator.data[FIELD_FW_REV])
            sw_version = "{0}.{1}.{2}".format(self.coordinator.data[FIELD_FW_MAJOR],
                                              self.coordinator.data[FIELD_FW_MINOR],
                                              self.coordinator.data[FIELD_FW_PATCH])
            self._attr_device_info[ATTR_HW_VERSION] = hw_version
            self._attr_device_info[ATTR_SW_VERSION] = sw_version
            self.async_schedule_update_ha_state()

            registry = async_get_device_registry(self.hass)
            if registry:
                device = registry.async_get_device(identifiers=self.device_info[ATTR_IDENTIFIERS])
                registry.async_update_device(device.id, hw_version=hw_version, sw_version=sw_version)

        super()._handle_coordinator_update()

    @property
    def extra_state_attributes(self) -> dict | None:
        rv = {
            CONF_HOST: self.client.host,
            CONF_PORT: self.client.port
        }
        if ATTR_HW_VERSION in self.device_info:
            rv[ATTR_HW_VERSION] = self.device_info[ATTR_HW_VERSION]
        if ATTR_SW_VERSION in self.device_info:
            rv[ATTR_SW_VERSION] = self.device_info[ATTR_SW_VERSION]
        if self.last_change:
            rv[STATE_LAST_CHANGE] = self.last_change.isoformat()
        return rv

    def handle_hw_info(self, fwinfo: dict) -> None:
        if fwinfo != self.coordinator.data:
            self.coordinator.async_set_updated_data(fwinfo)

    def on_ping(self, value: int) -> None:
        self._attr_native_value = value
        self.async_schedule_update_ha_state()

class PetDoorBattery(CoordinatorEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

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

        self.last_change = None

        self._attr_name = name
        self._attr_device_info = device
        self._attr_unique_id = f"{client.host}:{client.port}-battery"

        self.client.add_listener(self.unique_id, battery_update=self.handle_battery_update)
        self.client.add_handlers(name, on_connect=self.coordinator.async_request_refresh)

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

    @callback
    def handle_battery_update(self, battery_update: dict) -> None:
        if battery_update != self.coordinator.data:
            self.coordinator.async_set_updated_data(battery_update)

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

class PetDoorStats(CoordinatorEntity, SensorEntity):
    def __init__(self,
                 client: PowerPetDoorClient,
                 name: str,
                 sensor: dict,
                 coordinator: DataUpdateCoordinator,
                 device: DeviceInfo | None = None):
        super().__init__(coordinator)
        self.client = client
        self.sensor = sensor

        self.last_change = None
        self.power = True

        self._attr_name = name
        self._attr_entity_category = sensor.get("category")
        self._attr_state_class = sensor.get("class")
        self._attr_entity_registry_enabled_default = not sensor.get("disabled", False)
        self._attr_device_info = device
        self._attr_unique_id = f"{client.host}:{client.port}-{sensor['field']}"

        client.add_listener(name=self.unique_id,
                            stats_update={sensor["field"]: self.handle_state_update},
                            sensor_update={FIELD_POWER: self.handle_power_update})

    @property
    def available(self) -> bool:
        return (self.client.available and super().available and self.power)

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data[self.sensor["field"]]

    @property
    def extra_state_attributes(self) -> dict | None:
        rv = {}
        if self.last_change:
            rv[STATE_LAST_CHANGE] = self.last_change.isoformat()
        return rv

    @callback
    def _handle_coordinator_update(self) -> None:
        self.last_change = datetime.now(timezone.utc)
        super()._handle_coordinator_update()

    @callback
    def handle_state_update(self, state: float) -> None:
        if self.coordinator.data and state != self.coordinator.data[self.sensor["field"]]:
            changed = self.coordinator.data
            changed[self.sensor["field"]] = state
            self.coordinator.async_set_updated_data(changed)

    @callback
    def handle_power_update(self, state: bool) -> None:
        self.power = state
        if self.enabled:
            self.async_schedule_update_ha_state()

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
        PetDoorLatency(hass=hass,
                       client=obj["client"],
                       name=f"{name} Latency",
                       device=obj["device"],
                       update_interval=entry.options.get(CONF_REFRESH)),
        PetDoorBattery(hass=hass,
                       client=obj["client"],
                       name=f"{name} Battery",
                       device=obj["device"],
                       update_interval=entry.options.get(CONF_REFRESH)),
    ])

    async def update_stats() -> dict:
        _LOGGER.debug("Requesting update of stats")
        future = obj["client"].send_message(CONFIG, CMD_GET_DOOR_OPEN_STATS, notify=True)
        return await future

    timeout = entry.options.get(CONF_UPDATE)
    if not timeout:
        timeout = entry.options.get(CONF_REFRESH)

    stats_coordinator = DataUpdateCoordinator(
        hass=hass,
        logger=_LOGGER,
        name=f"{name} Stats",
        update_method=update_stats,
        update_interval=timedelta(timeout))

    obj["client"].add_handlers(f"{name} Stats", on_connect=stats_coordinator.async_request_refresh)

    async_add_entities([
        PetDoorStats(client=obj["client"],
                     name=f"{name} Total Open Cycles",
                     sensor=STATS["open_cycles"],
                     coordinator=stats_coordinator,
                     device=obj["device"]),
        PetDoorStats(client=obj["client"],
                     name=f"{name} Total Auto-Retracts",
                     sensor=STATS["auto_retracts"],
                     coordinator=stats_coordinator,
                     device=obj["device"]),
    ])
