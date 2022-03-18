from __future__ import annotations

import logging
import json
import copy

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
    _attr_should_poll = False
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = TIME_MILLISECONDS

    settings = {}

    update_settings_interval: float | None = None
    _update_settings = None

    def __init__(self,
                 coordinator: DataUpdateCoordinator,
                 client: PowerPetDoorClient,
                 device: DeviceInfo | None = None,
                 update_settings_interval: float | None = None) -> None:
        super().__init__(coordinator)
        self.client = client
        self.update_settings_interval = update_settings_interval

        self.client.on_connect = self.on_connect
        self.client.on_ping = self.on_ping
        self.client.on_disconnect = self.on_disconnect

        self._attr_name = coordinator.name
        self._attr_device_info = device
        self._attr_unique_id = f"{client.host}:{client.port}"

        self.client.add_listener(name=self.unique_id,
                                 door_status_update=coordinator.async_set_updated_data,
                                 settings_update=self.handle_settings,
                                 hw_info_update=self.handle_hw_info)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.client.start()

    async def async_will_remove_from_hass(self) -> None:
        self.client.stop()
        await super().async_will_remove_from_hass()

    @callback
    async def update_method(self) -> str:
        _LOGGER.debug("Requesting update of door status")
        future = self.send_message(CONFIG, CMD_GET_DOOR_STATUS, notify=True)
        return await future

    @property
    def available(self) -> bool:
        return self.client.available

    @property
    def icon(self) -> str | None:
        if self.available:
            if self.native_value is None:
                return "mdi:lan-pending"
            else:
                return "mdi:lan-connect"
        else:
            return "mdi:lan-disconnect"

    @property
    def extra_state_attributes(self) -> dict | None:
        rv = copy.deepcopy(self.settings)
        rv[CONF_HOST] = self.client.host
        rv[CONF_PORT] = self.client.port
        if self.coordinator.data:
            rv[FIELD_DOOR_STATUS] = self.coordinator.data
        if ATTR_HW_VERSION in self.device_info:
            rv[ATTR_HW_VERSION] = self.device_info[ATTR_HW_VERSION]
        if ATTR_SW_VERSION in self.device_info:
            rv[ATTR_SW_VERSION] = self.device_info[ATTR_SW_VERSION]
        return rv

    async def update_settings(self) -> None:
        _update_settings = self._update_settings
        await self.client.sleep(self.update_settings_interval)
        if _update_settings and not _update_settings.cancelled():
            # Wait between requesting info.
            self.client.send_message(CONFIG, CMD_GET_HW_INFO)
            await self.client.sleep(5.0)
            self.client.send_message(CONFIG, CMD_GET_SETTINGS)
            await self.client.sleep(5.0)
            self.client.send_message(CONFIG, CMD_GET_DOOR_BATTERY)


    def handle_settings(self, settings: dict) -> None:
        if self._update_settings:
            self._update_settings.cancel()
            self._update_settings = None

        self.settings = settings

        _LOGGER.info("DOOR SETTINGS - {}".format(json.dumps(self.settings)))
        self.async_schedule_update_ha_state(self.coordinator.data is None)
        if self.update_settings_interval:
            self._update_settings = self.client.ensure_future(self.update_settings())

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
        self.client.send_message(CONFIG, CMD_GET_SETTINGS)
        self.client.send_message(CONFIG, CMD_GET_DOOR_BATTERY)

    def on_disconnect(self) -> None:
        if self._update_settings:
            self._update_settings.cancel()
            self._update_settings = None

    def on_ping(self, value: int) -> None:
        self._attr_native_value = value
        self.async_schedule_update_ha_state()

class PetDoorBattery(SensorEntity):
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_should_poll = False

    ac_present = False
    battery_present = False

    last_change = None
    def __init__(self,
                 client: PowerPetDoorClient,
                 name: str,
                 device: DeviceInfo | None = None) -> None:
        self.client = client

        self._attr_name = name
        self._attr_device_info = device
        self._attr_unique_id = f"{client.host}:{client.port}-battery"

        client.add_listener(name=self.unique_id, battery_update=self.handle_battery_update)

    @callback
    async def async_update(self) -> None:
        _LOGGER.debug("Requesting update of door battery status")
        self.client.send_message(CONFIG, CMD_GET_DOOR_BATTERY)

    @property
    def available(self) -> bool:
        return (self.client.available and self.battery_present)

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

    def handle_battery_update(self, battery: dict) -> None:
        if self._attr_native_value is not None and self._attr_native_value != battery[FIELD_BATTERY_PERCENT]:
            self.last_change = datetime.now(timezone.utc)
        self._attr_native_value = battery[FIELD_BATTERY_PERCENT]
        self.battery_present = battery[FIELD_BATTERY_PRESENT]
        self.ac_present = battery[FIELD_AC_PRESENT]
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
        PetDoorCoordinator(coordinator=obj["coordinator"],
                           client=obj["client"],
                           device=obj["device"],
                           update_settings_interval=entry.options.get(CONF_REFRESH, entry.data.get(CONF_REFRESH))),
        PetDoorBattery(client=obj["client"],
                       name=f"{name} - Battery",
                       device=obj["device"]),
    ])
