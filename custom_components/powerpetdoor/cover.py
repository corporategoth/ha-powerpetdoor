# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""Cover entity for the Power Pet Door."""

from __future__ import annotations

from typing import Any

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityDescription,
    CoverEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from powerpetdoor import CommandError, DoorStatus

from .const import DOMAIN
from .coordinator import PowerPetDoorConfigEntry, PowerPetDoorCoordinator
from .entity import PowerPetDoorPoweredEntity

PARALLEL_UPDATES = 1

#: Door states that mean the flap is on its way up. The facade exposes
#: `is_closing` but not `is_opening`, so this is derived here - and derived
#: from the enum rather than from raw strings, so a renamed state is a
#: NameError at import rather than a cover that silently never reports
#: opening.
_OPENING_STATES = frozenset({DoorStatus.RISING, DoorStatus.SLOWING})


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowerPetDoorConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Power Pet Door cover."""
    async_add_entities([PowerPetDoorCover(entry.runtime_data)])


class PowerPetDoorCover(PowerPetDoorPoweredEntity, CoverEntity):
    """The pet door flap itself."""

    entity_description = CoverEntityDescription(
        key="door",
        translation_key="door",
        # SHUTTER, not DOOR: the flap is driven vertically by a motor and
        # reports intermediate positions, which is what a shutter is. This
        # also matches what previous versions shipped, so existing
        # dashboards and voice assistants keep behaving the same way.
        device_class=CoverDeviceClass.SHUTTER,
    )
    _attr_supported_features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE

    def __init__(self, coordinator: PowerPetDoorCoordinator) -> None:
        """Initialise the cover."""
        super().__init__(coordinator, self.entity_description.key)

    @property
    def current_cover_position(self) -> int | None:
        """How far open the flap is, 0-100."""
        return self.coordinator.door.position

    @property
    def is_closed(self) -> bool:
        """Whether the flap is fully down."""
        return self.coordinator.door.is_closed

    @property
    def is_closing(self) -> bool:
        """Whether the flap is on its way down."""
        return self.coordinator.door.is_closing

    @property
    def is_opening(self) -> bool:
        """Whether the flap is on its way up."""
        return self.coordinator.door.status in _OPENING_STATES

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the flap and hold it open.

        `open()`, which since pypowerpetdoor 0.4.1 means "open and stay
        open". A cover that closed itself on a hold timer would report open
        and then go closed with no command behind it, which no automation
        could reason about. The timed open is the "Open and auto-close"
        button instead.
        """
        await self._async_command(self.coordinator.door.open())

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the flap."""
        await self._async_command(self.coordinator.door.close())

    async def _async_command(self, awaitable: Any) -> None:
        """Await a door command, surfacing failures to the user."""
        try:
            await awaitable
        except (CommandError, OSError, TimeoutError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        self.coordinator.async_update_listeners()
