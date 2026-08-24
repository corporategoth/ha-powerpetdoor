# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""Number entities for the Power Pet Door."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import EntityCategory, UnitOfElectricPotential, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from powerpetdoor import CommandError, PowerPetDoor

from .const import (
    CONF_HOLD_MAX,
    CONF_HOLD_MIN,
    CONF_HOLD_STEP,
    DEFAULT_HOLD_MAX,
    DEFAULT_HOLD_MIN,
    DEFAULT_HOLD_STEP,
    DOMAIN,
)
from .coordinator import PowerPetDoorConfigEntry, PowerPetDoorCoordinator
from .entity import PowerPetDoorEntity

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class PowerPetDoorNumberDescription(NumberEntityDescription):
    """Describes one Power Pet Door number."""

    value_fn: Callable[[PowerPetDoor], float]
    set_fn: Callable[[PowerPetDoor, float], Awaitable[None]]


#: The sensor trigger voltages are in millivolts on the wire and the facade
#: keeps them that way. They are presented in volts because that is the unit
#: HA's NumberDeviceClass.VOLTAGE means, and a "voltage" reading of 1500 V
#: on a battery-powered pet door would be nonsense on a dashboard.
_MV_PER_V = 1000.0

NUMBERS: tuple[PowerPetDoorNumberDescription, ...] = (
    PowerPetDoorNumberDescription(
        key="hold_open_time",
        translation_key="hold_open_time",
        entity_category=EntityCategory.CONFIG,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=NumberDeviceClass.DURATION,
        mode=NumberMode.SLIDER,
        value_fn=lambda door: door.hold_time,
        set_fn=lambda door, value: door.set_hold_time(value),
    ),
    PowerPetDoorNumberDescription(
        key="sensor_trigger_voltage",
        translation_key="sensor_trigger_voltage",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=NumberDeviceClass.VOLTAGE,
        mode=NumberMode.BOX,
        native_min_value=0.0,
        native_max_value=5.0,
        native_step=0.001,
        value_fn=lambda door: door.sensor_trigger_voltage / _MV_PER_V,
        set_fn=lambda door, value: door.set_sensor_trigger_voltage(round(value * _MV_PER_V)),
    ),
    PowerPetDoorNumberDescription(
        key="sleep_sensor_trigger_voltage",
        translation_key="sleep_sensor_trigger_voltage",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=NumberDeviceClass.VOLTAGE,
        mode=NumberMode.BOX,
        native_min_value=0.0,
        native_max_value=5.0,
        native_step=0.001,
        value_fn=lambda door: door.sleep_sensor_trigger_voltage / _MV_PER_V,
        set_fn=lambda door, value: door.set_sleep_sensor_trigger_voltage(round(value * _MV_PER_V)),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowerPetDoorConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Power Pet Door numbers."""
    coordinator = entry.runtime_data
    async_add_entities(PowerPetDoorNumber(coordinator, description) for description in NUMBERS)


class PowerPetDoorNumber(PowerPetDoorEntity, NumberEntity):
    """A door setting exposed as a number."""

    entity_description: PowerPetDoorNumberDescription

    def __init__(
        self,
        coordinator: PowerPetDoorCoordinator,
        description: PowerPetDoorNumberDescription,
    ) -> None:
        """Initialise the number."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

        # The hold-open bounds are user configuration, not device facts: the
        # door's own app offers 2-8s in 2s steps but the hardware accepts a
        # much wider range, and people asked for the wider range. Applied
        # per-entity here rather than by mutating the shared description -
        # the old code assigned into the module-level NUMBERS dict, so with
        # two doors configured the second one's options silently overwrote
        # the first one's.
        if description.key == "hold_open_time":
            options = coordinator.config_entry.options
            self._attr_native_min_value = options.get(CONF_HOLD_MIN, DEFAULT_HOLD_MIN)
            self._attr_native_max_value = options.get(CONF_HOLD_MAX, DEFAULT_HOLD_MAX)
            self._attr_native_step = options.get(CONF_HOLD_STEP, DEFAULT_HOLD_STEP)

    @property
    def native_value(self) -> float:
        """Return the door's current value for this setting."""
        return self.entity_description.value_fn(self.coordinator.door)

    async def async_set_native_value(self, value: float) -> None:
        """Push a new value to the door."""
        try:
            await self.entity_description.set_fn(self.coordinator.door, value)
        except (CommandError, OSError, TimeoutError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        self.coordinator.async_update_listeners()
