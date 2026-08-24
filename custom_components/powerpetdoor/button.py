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


BUTTONS: tuple[PowerPetDoorButtonDescription, ...] = (
    # Opens and STAYS open until something closes it. Since pypowerpetdoor
    # 0.4.1 that is what `open()` means - it sends OPEN_AND_HOLD and parks
    # the door in KEEPUP. (Before 0.4.1, `open()` was the timed open and
    # `open_and_hold()` was this; the library renamed them so the obvious
    # call is the one that does the obvious thing.)
    PowerPetDoorButtonDescription(
        key="open",
        translation_key="open",
        press_fn=lambda door: door.open(),
    ),
    PowerPetDoorButtonDescription(
        key="close",
        translation_key="close",
        press_fn=lambda door: door.close(),
    ),
    # The timed open: the door rises, sits in HOLDING for the configured
    # hold time, then closes itself - exactly what a pet triggering a sensor
    # gets. Distinct from `open()` since 0.4.1; they send different commands
    # (OPEN vs OPEN_AND_HOLD), so these two buttons are genuinely different
    # and neither is redundant.
    PowerPetDoorButtonDescription(
        key="cycle",
        translation_key="cycle",
        press_fn=lambda door: door.cycle(),
    ),
    # Open if closed, close if open, do nothing mid-travel. The old
    # integration had exactly one button whose behaviour depended on the
    # door's state and called it "Cycle"; that is a toggle, and conflating
    # the two made automations non-deterministic. They are separate here and
    # each does one thing.
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
