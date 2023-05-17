from __future__ import annotations

from datetime import datetime, timezone, timedelta

from homeassistant.core import HomeAssistant, callback
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, CoordinatorEntity
from homeassistant.config_entries import ConfigEntry, SOURCE_IMPORT
from homeassistant.components.number import NumberEntity, NumberDeviceClass
from .client import PowerPetDoorClient

from homeassistant.const import UnitOfTime, UnitOfElectricPotential

from .const import (
    DOMAIN,
    CONF_HOST,
    CONF_PORT,
    CONF_NAME,
    CONFIG,
    STATE_LAST_CHANGE,
    FIELD_POWER,
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
        "get": CMD_GET_HOLD_TIME,
        "set": CMD_SET_HOLD_TIME,
        "icon": "mdi:timer-outline",
        "category": EntityCategory.CONFIG,
        "multiplier": 0.01,
        "min": 2,
        "max": 8,
        "step": 1,
        "unit_of_measurement": UnitOfTime.SECONDS,
    },
    "sensor_trigger_voltage": {
        "field": FIELD_SENSOR_TRIGGER_VOLTAGE,
        "get": CMD_GET_SENSOR_TRIGGER_VOLTAGE,
        "set": CMD_SET_SENSOR_TRIGGER_VOLTAGE,
        "icon": "mdi:high-voltage",
        "multiplier": 0.001,
        "class": NumberDeviceClass.VOLTAGE,
        "category": EntityCategory.CONFIG,
        "unit_of_measurement": UnitOfElectricPotential.VOLT,
        "disabled": True,
    },
    "sleep_sensor_trigger_voltage": {
        "field": FIELD_SLEEP_SENSOR_TRIGGER_VOLTAGE,
        "get": CMD_GET_SLEEP_SENSOR_TRIGGER_VOLTAGE,
        "set": CMD_SET_SLEEP_SENSOR_TRIGGER_VOLTAGE,
        "icon": "mdi:high-voltage",
        "multiplier": 0.001,
        "class": NumberDeviceClass.VOLTAGE,
        "category": EntityCategory.CONFIG,
        "unit_of_measurement": UnitOfElectricPotential.VOLT,
        "disabled": True,
    },
}

class PetDoorNumber(CoordinatorEntity, NumberEntity):
    last_change = None
    power = True
    multiplier = 1.0

    def __init__(self,
                 client: PowerPetDoorClient,
                 name: str,
                 number: dict,
                 coordinator: DataUpdateCoordinator,
                 device: DeviceInfo | None = None) -> None:
        super().__init__(coordinator)
        self.client = client
        self.number = number

        self._attr_name = name
        if "category" in number:
            self._attr_entity_category = number["category"]
        if "class" in number:
            self._attr_device_class = number["class"]
        if "min" in number:
            self._attr_native_min_value = number["min"]
        if "max" in number:
            self._attr_native_max_value = number["max"]
        if "step" in number:
            self._attr_native_step = number["step"]
        if "unit" in number:
            self._attr_native_unit_of_measurement = number["unit"]
        if "disabled" in number:
            self._attr_entity_registry_visible_default = not number["disabled"]
        if "multiplier" in number:
            self.multiplier = number["multiplier"]
        self._attr_device_info = device
        self._attr_unique_id = f"{client.host}:{client.port}-{number['field']}"

        client.add_listener(name=self.unique_id, sensor_update={number["field"]: self.handle_state_update,
                                                                FIELD_POWER: self.handle_power_update})

    @property
    def available(self) -> bool:
        return (self.client.available and super().available and self.power)

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data[self.number["field"]] * self.multiplier

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
        if self.coordinator.data and state != self.coordinator.data[self.number["field"]]:
            changed = self.coordinator.data
            changed[self.number["field"]] = state
            self.coordinator.async_set_updated_data(changed)

    @callback
    def handle_power_update(self, state: bool) -> None:
        self.power = state
        self.async_schedule_update_ha_state()

    async def async_set_native_value(self, value: float) -> None:
        """Open the cover."""
        self.client.send_message(CONFIG, self.number['set'], **{self.number['field']: value / self.multiplier})

# Right now this can be an alias for the above
async def async_setup_entry(hass: HomeAssistant,
                            entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:

    host = entry.data.get(CONF_HOST)
    port = entry.data.get(CONF_PORT)
    name = entry.data.get(CONF_NAME)
    obj = hass.data[DOMAIN][f"{host}:{port}"]

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
