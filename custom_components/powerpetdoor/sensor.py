# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""Sensor entities for the Power Pet Door."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from powerpetdoor import DoorStatus, PowerPetDoor

from .coordinator import PowerPetDoorConfigEntry, PowerPetDoorCoordinator
from .entity import PowerPetDoorEntity

# Read-only; nothing here talks to the door.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class PowerPetDoorSensorDescription(SensorEntityDescription):
    """Describes one Power Pet Door sensor."""

    value_fn: Callable[[PowerPetDoor], float | str | None]


SENSORS: tuple[PowerPetDoorSensorDescription, ...] = (
    PowerPetDoorSensorDescription(
        key="battery",
        translation_key="battery",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        # A door with no battery fitted reports 0%, which would otherwise
        # look like a flat battery on every dashboard and fire every
        # low-battery automation. None means "no reading", which is the
        # truth.
        value_fn=lambda door: door.battery.percent if door.battery.present else None,
    ),
    PowerPetDoorSensorDescription(
        key="latency",
        translation_key="latency",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        device_class=SensorDeviceClass.DURATION,
        # `PowerPetDoor.latency` is documented, and implemented, in SECONDS
        # (`_on_ping` stores `latency_ms / 1000.0`). Declaring milliseconds
        # and returning it unconverted displayed a 47 ms link as "0.047 ms"
        # - wrong by 1000x, and plausible enough at a glance to be believed.
        # Milliseconds is kept as the unit because that is the useful scale
        # for a LAN round trip; the conversion is what was missing.
        value_fn=lambda door: None if door.latency is None else door.latency * 1000,
    ),
    # The raw door state. The cover entity models the flap for automations;
    # this exposes the state machine underneath it, which is what a bug
    # report needs and what the cover's four booleans cannot express (a
    # door can be HOLDING or KEEPUP and both read as "open").
    PowerPetDoorSensorDescription(
        key="status",
        translation_key="status",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.ENUM,
        options=[status.name.lower() for status in DoorStatus],
        value_fn=lambda door: door.status.name.lower(),
    ),
    PowerPetDoorSensorDescription(
        key="total_open_cycles",
        translation_key="total_open_cycles",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_registry_enabled_default=False,
        value_fn=lambda door: door.total_open_cycles,
    ),
    PowerPetDoorSensorDescription(
        key="total_auto_retracts",
        translation_key="total_auto_retracts",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_registry_enabled_default=False,
        value_fn=lambda door: door.total_auto_retracts,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowerPetDoorConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Power Pet Door sensors."""
    coordinator = entry.runtime_data
    async_add_entities(PowerPetDoorSensor(coordinator, description) for description in SENSORS)


class PowerPetDoorSensor(PowerPetDoorEntity, SensorEntity):
    """A read-only value from the door."""

    entity_description: PowerPetDoorSensorDescription

    def __init__(
        self,
        coordinator: PowerPetDoorCoordinator,
        description: PowerPetDoorSensorDescription,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | str | None:
        """Return the current reading."""
        return self.entity_description.value_fn(self.coordinator.door)
