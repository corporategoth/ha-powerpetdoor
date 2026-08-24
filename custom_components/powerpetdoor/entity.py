# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""Shared base class for every Power Pet Door entity."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import PowerPetDoorCoordinator


class PowerPetDoorEntity(CoordinatorEntity[PowerPetDoorCoordinator]):
    """Base for every entity this integration exposes.

    Carries the three things platinum requires of all of them - a stable
    unique_id, `has_entity_name` with a translation key, and device info -
    so no platform can forget one.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: PowerPetDoorCoordinator, key: str) -> None:
        """Bind to the coordinator and take `key` as the entity's identity.

        `key` is both the translation key and the unique_id suffix, on
        purpose: it makes it impossible to add an entity whose name comes
        from `strings.json` under one name while its registry entry is
        filed under another.
        """
        super().__init__(coordinator)
        self._attr_translation_key = key
        self._attr_unique_id = f"{coordinator.device_identifier}-{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.device_identifier)},
            manufacturer=MANUFACTURER,
            model=MODEL,
            name=coordinator.config_entry.title,
            sw_version=coordinator.door.firmware_version or None,
            hw_version=coordinator.door.hardware_version or None,
            configuration_url=None,
        )

    @property
    def available(self) -> bool:
        """Whether the door is reachable *and* the last refresh succeeded.

        Deliberately not gated on `door.power`. Powering the door off is a
        thing the user did on purpose and the door keeps answering while
        off, so hiding every entity behind it - as previous versions did -
        removed the very switch needed to turn it back on and made the rest
        report "unavailable" for a door that was answering perfectly well.
        Entities whose value is genuinely meaningless with the power off say
        so through their own state, not through availability.
        """
        return self.coordinator.door.connected and super().available


class PowerPetDoorPoweredEntity(PowerPetDoorEntity):
    """An entity whose function genuinely stops when the door is powered off.

    The motor, its sensors and the schedule engine do nothing while the door
    is powered down, so a state for them would be a fiction. Configuration
    the door still remembers - and the power switch itself - must NOT use
    this class.
    """

    @property
    def available(self) -> bool:
        """Reachable, refreshed, and the door's motor actually powered."""
        return super().available and self.coordinator.door.power
