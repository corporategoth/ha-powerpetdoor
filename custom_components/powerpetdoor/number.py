# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""Number entities for Power Pet Door."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

from homeassistant.core import HomeAssistant, callback
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, CoordinatorEntity
from homeassistant.config_entries import ConfigEntry, SOURCE_IMPORT
from homeassistant.components.number import NumberEntity, NumberDeviceClass, NumberMode, DEFAULT_MIN_VALUE, DEFAULT_MAX_VALUE, DEFAULT_STEP
from .client import PowerPetDoorClient

from homeassistant.const import UnitOfTime, UnitOfElectricPotential

from .const import (
    DOMAIN,
    CONF_HOST,
    CONF_PORT,
    CONF_NAME,
    CONF_HOLD_MIN,
    CONF_HOLD_MAX,
    CONF_HOLD_STEP,
    CONFIG,
    STATE_LAST_CHANGE,
    FIELD_POWER,
    FIELD_HOLD_TIME,
    FIELD_VOLTAGE,
    FIELD_HOLD_OPEN_TIME,
    FIELD_SENSOR_TRIGGER_VOLTAGE,
    FIELD_SLEEP_SENSOR_TRIGGER_VOLTAGE,
    CMD_GET_HOLD_TIME,
    CMD_SET_HOLD_TIME,
    CMD_GET_SENSOR_TRIGGER_VOLTAGE,
    CMD_SET_SENSOR_TRIGGER_VOLTAGE,
    CMD_GET_SLEEP_SENSOR_TRIGGER_VOLTAGE,
    CMD_SET_SLEEP_SENSOR_TRIGGER_VOLTAGE,
)

import logging

_LOGGER = logging.getLogger(__name__)

NUMBERS = {
    "hold_open_time": {
        "field": FIELD_HOLD_OPEN_TIME,
        "getset_field": FIELD_HOLD_TIME,
        "get": CMD_GET_HOLD_TIME,
        "set": CMD_SET_HOLD_TIME,
        "icon": "mdi:timer-outline",
        "category": EntityCategory.CONFIG,
        "multiplier": 0.01,
        "mode": NumberMode.SLIDER,
        "unit_of_measurement": UnitOfTime.SECONDS,
        "update": "hold_time_update",
    },
    "sensor_trigger_voltage": {
        "field": FIELD_SENSOR_TRIGGER_VOLTAGE,
        "getset_field": FIELD_VOLTAGE,
        "get": CMD_GET_SENSOR_TRIGGER_VOLTAGE,
        "set": CMD_SET_SENSOR_TRIGGER_VOLTAGE,
        "icon": "mdi:high-voltage",
        "multiplier": 0.001,
        "mode": NumberMode.BOX,
        "class": NumberDeviceClass.VOLTAGE,
        "category": EntityCategory.CONFIG,
        "unit_of_measurement": UnitOfElectricPotential.VOLT,
        "update": "sensor_trigger_voltage_update",
        "disabled": True,
    },
    "sleep_sensor_trigger_voltage": {
        "field": FIELD_SLEEP_SENSOR_TRIGGER_VOLTAGE,
        "getset_field": FIELD_VOLTAGE,
        "get": CMD_GET_SLEEP_SENSOR_TRIGGER_VOLTAGE,
        "set": CMD_SET_SLEEP_SENSOR_TRIGGER_VOLTAGE,
        "icon": "mdi:high-voltage",
        "multiplier": 0.001,
        "mode": NumberMode.BOX,
        "class": NumberDeviceClass.VOLTAGE,
        "category": EntityCategory.CONFIG,
        "unit_of_measurement": UnitOfElectricPotential.VOLT,
        "update": "sleep_sensor_trigger_voltage_update",
        "disabled": True,
    },
}

class PetDoorNumber(CoordinatorEntity, NumberEntity):
    def __init__(self,
                 client: PowerPetDoorClient,
                 name: str,
                 number: dict,
                 coordinator: DataUpdateCoordinator,
                 device: DeviceInfo | None = None) -> None:
        super().__init__(coordinator)
        self.client = client
        self.number = number

        self.last_change = None
        self.power = True

        self.multiplier = number.get("multiplier", 1.0)

        self._attr_name = name
        self._attr_entity_category = number.get("category")
        self._attr_device_class = number.get("class")
        self._attr_native_unit_of_measurement = number.get("unit")
        self._attr_native_min_value = number.get("min", DEFAULT_MIN_VALUE)
        self._attr_native_max_value = number.get("max", DEFAULT_MAX_VALUE)
        self._attr_native_step = number.get("step", DEFAULT_STEP)
        self._attr_mode = number.get("mode", NumberMode.AUTO)
        self._attr_entity_registry_enabled_default = not number.get("disabled", False)
        self._attr_device_info = device
        self._attr_unique_id = f"{client.host}:{client.port}-{number['field']}"

        client.add_listener(name=self.unique_id, **{number["update"]: self.handle_state_update},
                            sensor_update={FIELD_POWER: self.handle_power_update})

    @property
    def available(self) -> bool:
        return (self.client.available and super().available and self.power)

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        return float(self.coordinator.data[self.number["field"]]) * self.multiplier

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
    def handle_state_update(self, state: int) -> None:
        if self.coordinator.data and state != self.coordinator.data[self.number["field"]]:
            changed = self.coordinator.data
            changed[self.number["field"]] = state
            self.coordinator.async_set_updated_data(changed)

    @callback
    def handle_power_update(self, state: bool) -> None:
        self.power = state
        if self.enabled:
            self.async_schedule_update_ha_state()

    async def async_set_native_value(self, value: float) -> None:
        """Open the cover."""
        field = self.number.get("getset_field", self.number.get("field"))
        self.client.send_message(CONFIG, self.number['set'], **{field: int(value / self.multiplier)})

# Right now this can be an alias for the above
async def async_setup_entry(hass: HomeAssistant,
                            entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:

    host = entry.data.get(CONF_HOST)
    port = entry.data.get(CONF_PORT)
    name = entry.data.get(CONF_NAME)
    obj = hass.data[DOMAIN][f"{host}:{port}"]

    NUMBERS["hold_open_time"]["min"] = entry.options.get(CONF_HOLD_MIN)
    NUMBERS["hold_open_time"]["max"] = entry.options.get(CONF_HOLD_MAX)
    NUMBERS["hold_open_time"]["step"] = entry.options.get(CONF_HOLD_STEP)

    async_add_entities([
        PetDoorNumber(client=obj["client"],
                      name=f"{name} Hold Open Time",
                      number=NUMBERS["hold_open_time"],
                      coordinator=obj["settings"],
                      device=obj["device"]),
        PetDoorNumber(client=obj["client"],
                      name=f"{name} Sensor Trigger Voltage",
                      number=NUMBERS["sensor_trigger_voltage"],
                      coordinator=obj["settings"],
                      device=obj["device"]),
        PetDoorNumber(client=obj["client"],
                      name=f"{name} Sleep Sensor Trigger Voltage",
                      number=NUMBERS["sleep_sensor_trigger_voltage"],
                      coordinator=obj["settings"],
                      device=obj["device"]),
    ])
