# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""Button entities for the Power Pet Door."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from powerpetdoor import CommandError, PowerPetDoor

from .const import DOMAIN
from .coordinator import PowerPetDoorConfigEntry, PowerPetDoorCoordinator
from .entity import PowerPetDoorPoweredEntity

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class PowerPetDoorButtonDescription(ButtonEntityDescription):
    """Describes one Power Pet Door button."""

    press_fn: Callable[[PowerPetDoor], Awaitable[None]]


# There are deliberately no Open and Close buttons. `door.open()` and
# `door.close()` are precisely what `cover.open_cover` and
# `cover.close_cover` already call on the door entity, so buttons for them
# would be a second control for the same two actions - a thing to keep in
# sync on every dashboard, and one more pair of entities for an automation
# author to pick the wrong one of. The cover is the door; these two are the
# actions a cover has no way to express.
BUTTONS: tuple[PowerPetDoorButtonDescription, ...] = (
    # The timed open: the door rises, sits in HOLDING for the configured
    # hold time, then closes itself - exactly what a pet triggering a sensor
    # gets. `cover.open_cover` sends OPEN_AND_HOLD and leaves the door up
    # until something closes it, so a cover cannot ask for this.
    PowerPetDoorButtonDescription(
        key="cycle",
        translation_key="cycle",
        press_fn=lambda door: door.cycle(),
    ),
    # Open if closed, close if open, do nothing mid-travel. This is what the
    # old integration's single button did, despite being labelled "Cycle" -
    # which is why `migration.py` maps that entity onto this one and not
    # onto the button that inherited its label.
    PowerPetDoorButtonDescription(
        key="toggle",
        translation_key="toggle",
        press_fn=lambda door: door.toggle(),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowerPetDoorConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Power Pet Door buttons."""
    coordinator = entry.runtime_data
    async_add_entities(PowerPetDoorButton(coordinator, description) for description in BUTTONS)


class PowerPetDoorButton(PowerPetDoorPoweredEntity, ButtonEntity):
    """A button that sends one door command."""

    entity_description: PowerPetDoorButtonDescription

    def __init__(
        self,
        coordinator: PowerPetDoorCoordinator,
        description: PowerPetDoorButtonDescription,
    ) -> None:
        """Initialise the button."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        """Send the command."""
        try:
            await self.entity_description.press_fn(self.coordinator.door)
        except (CommandError, OSError, TimeoutError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        self.coordinator.async_update_listeners()
