# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""Switch entities for the Power Pet Door."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from powerpetdoor import CommandError, PowerPetDoor

from .const import DOMAIN
from .coordinator import PowerPetDoorConfigEntry, PowerPetDoorCoordinator
from .entity import PowerPetDoorEntity, PowerPetDoorPoweredEntity

# Every write goes to one device over one socket; the library serialises
# them anyway. Letting Home Assistant fire them concurrently would only
# queue them deeper.
PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class PowerPetDoorSwitchDescription(SwitchEntityDescription):
    """Describes one Power Pet Door switch."""

    value_fn: Callable[[PowerPetDoor], bool]
    set_fn: Callable[[PowerPetDoor, bool], Awaitable[None]]
    #: True when the door being powered off makes this switch meaningless.
    #: The power switch itself and the notification switches are not gated,
    #: or turning the door back on would be impossible.
    needs_power: bool = True


SWITCHES: tuple[PowerPetDoorSwitchDescription, ...] = (
    PowerPetDoorSwitchDescription(
        key="power",
        translation_key="power",
        device_class=SwitchDeviceClass.SWITCH,
        value_fn=lambda door: door.power,
        set_fn=lambda door, on: door.set_power(on),
        # Never gated: this is the switch that turns the power back on.
        needs_power=False,
    ),
    PowerPetDoorSwitchDescription(
        key="inside_sensor",
        translation_key="inside_sensor",
        device_class=SwitchDeviceClass.SWITCH,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda door: door.inside_sensor,
        set_fn=lambda door, on: door.set_inside_sensor(on),
    ),
    PowerPetDoorSwitchDescription(
        key="outside_sensor",
        translation_key="outside_sensor",
        device_class=SwitchDeviceClass.SWITCH,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda door: door.outside_sensor,
        set_fn=lambda door, on: door.set_outside_sensor(on),
    ),
    PowerPetDoorSwitchDescription(
        key="auto",
        translation_key="auto",
        device_class=SwitchDeviceClass.SWITCH,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda door: door.auto,
        set_fn=lambda door, on: door.set_auto(on),
    ),
    PowerPetDoorSwitchDescription(
        key="outside_safety_lock",
        translation_key="outside_safety_lock",
        device_class=SwitchDeviceClass.SWITCH,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        value_fn=lambda door: door.safety_lock,
        set_fn=lambda door, on: door.set_safety_lock(on),
    ),
    PowerPetDoorSwitchDescription(
        key="auto_retract",
        translation_key="auto_retract",
        device_class=SwitchDeviceClass.SWITCH,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        value_fn=lambda door: door.autoretract,
        set_fn=lambda door, on: door.set_autoretract(on),
    ),
    # The wire calls this "cmd lockout" and inverts it. The facade already
    # presents it the way a user thinks about it - "keep the door open while
    # a pet is near" - so this integration does NOT re-invert it. Previous
    # versions carried an `inverted` flag here and got the polarity from
    # const.py; that logic now lives in exactly one place, the library.
    PowerPetDoorSwitchDescription(
        key="pet_proximity_keep_open",
        translation_key="pet_proximity_keep_open",
        device_class=SwitchDeviceClass.SWITCH,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        value_fn=lambda door: door.pet_proximity_keep_open,
        set_fn=lambda door, on: door.set_pet_proximity_keep_open(on),
    ),
)

#: The five notification toggles. They are a separate table because the
#: door sets them as one message - `set_notifications(**kwargs)` - so each
#: switch has to name its own keyword rather than call a dedicated setter.
NOTIFICATION_SWITCHES: tuple[PowerPetDoorSwitchDescription, ...] = (
    PowerPetDoorSwitchDescription(
        key="notify_inside_on",
        translation_key="notify_inside_on",
        device_class=SwitchDeviceClass.SWITCH,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        value_fn=lambda door: door.notifications.inside_on,
        set_fn=lambda door, on: door.set_notifications(inside_on=on),
        needs_power=False,
    ),
    PowerPetDoorSwitchDescription(
        key="notify_inside_off",
        translation_key="notify_inside_off",
        device_class=SwitchDeviceClass.SWITCH,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        value_fn=lambda door: door.notifications.inside_off,
        set_fn=lambda door, on: door.set_notifications(inside_off=on),
        needs_power=False,
    ),
    PowerPetDoorSwitchDescription(
        key="notify_outside_on",
        translation_key="notify_outside_on",
        device_class=SwitchDeviceClass.SWITCH,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        value_fn=lambda door: door.notifications.outside_on,
        set_fn=lambda door, on: door.set_notifications(outside_on=on),
        needs_power=False,
    ),
    PowerPetDoorSwitchDescription(
        key="notify_outside_off",
        translation_key="notify_outside_off",
        device_class=SwitchDeviceClass.SWITCH,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        value_fn=lambda door: door.notifications.outside_off,
        set_fn=lambda door, on: door.set_notifications(outside_off=on),
        needs_power=False,
    ),
    PowerPetDoorSwitchDescription(
        key="notify_low_battery",
        translation_key="notify_low_battery",
        device_class=SwitchDeviceClass.SWITCH,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        value_fn=lambda door: door.notifications.low_battery,
        set_fn=lambda door, on: door.set_notifications(low_battery=on),
        needs_power=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowerPetDoorConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Power Pet Door switches."""
    coordinator = entry.runtime_data
    entities: list[SwitchEntity] = [
        PowerPetDoorSwitch(coordinator, description)
        if not description.needs_power
        else PowerPetDoorPoweredSwitch(coordinator, description)
        for description in (*SWITCHES, *NOTIFICATION_SWITCHES)
    ]
    entities.append(PowerPetDoorConnectionSwitch(coordinator))
    async_add_entities(entities)


class _SwitchMixin:
    """The behaviour shared by the gated and ungated switch classes.

    Split this way because availability is decided by which BASE class an
    entity inherits (`PowerPetDoorEntity` vs `PowerPetDoorPoweredEntity`),
    and Python has no way to pick a base at runtime from a dataclass field
    without this small amount of ceremony. The alternative - one class with
    an `if self.entity_description.needs_power` inside `available` -
    duplicates the base classes' logic in a third place.
    """

    entity_description: PowerPetDoorSwitchDescription
    coordinator: PowerPetDoorCoordinator

    @property
    def is_on(self) -> bool:
        """Return the door's current setting for this switch."""
        return self.entity_description.value_fn(self.coordinator.door)

    async def _async_set(self, state: bool) -> None:
        """Push a new setting to the door, surfacing failures to the user."""
        try:
            await self.entity_description.set_fn(self.coordinator.door, state)
        except (CommandError, OSError, TimeoutError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        # The door echoes the change back as a push, but not always
        # instantly; writing state now keeps the toggle from springing back
        # under the user's finger while that round trip completes.
        self.coordinator.async_update_listeners()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self._async_set(False)


class PowerPetDoorSwitch(_SwitchMixin, PowerPetDoorEntity, SwitchEntity):
    """A switch that works regardless of whether the door is powered."""

    entity_description: PowerPetDoorSwitchDescription

    def __init__(
        self,
        coordinator: PowerPetDoorCoordinator,
        description: PowerPetDoorSwitchDescription,
    ) -> None:
        """Initialise the switch."""
        super().__init__(coordinator, description.key)
        self.entity_description = description


class PowerPetDoorPoweredSwitch(_SwitchMixin, PowerPetDoorPoweredEntity, SwitchEntity):
    """A switch that is unavailable while the door's motor is powered off."""

    entity_description: PowerPetDoorSwitchDescription

    def __init__(
        self,
        coordinator: PowerPetDoorCoordinator,
        description: PowerPetDoorSwitchDescription,
    ) -> None:
        """Initialise the switch."""
        super().__init__(coordinator, description.key)
        self.entity_description = description


class PowerPetDoorConnectionSwitch(PowerPetDoorEntity, SwitchEntity):
    """Whether Home Assistant holds the connection to the door.

    The door accepts one client at a time, so while Home Assistant is
    connected the manufacturer's phone app cannot be. Turning this off frees
    the door for the app and stops the library reconnecting; turning it back
    on reconnects without a Home Assistant restart. That capability was
    added in response to issue #18 and would otherwise have been lost in the
    move to a coordinator-owned connection.

    Crucially it does NOT own the lifecycle. Setup connects, and this switch
    only toggles afterwards. The previous design put `client.start()` in an
    entity's `async_added_to_hass`, which is why disabling an entity could
    take the whole integration offline - the failure behind issue #18 in the
    first place.

    This entity also replaces the separate connectivity binary sensor: a
    switch already reports the state it controls, and two entities showing
    one value is one entity too many.
    """

    entity_description = SwitchEntityDescription(
        key="connection",
        translation_key="connection",
        device_class=SwitchDeviceClass.SWITCH,
        entity_category=EntityCategory.CONFIG,
    )

    def __init__(self, coordinator: PowerPetDoorCoordinator) -> None:
        """Initialise the connection switch."""
        super().__init__(coordinator, self.entity_description.key)

    @property
    def available(self) -> bool:
        """Always. This is the control that gets the connection back."""
        return True

    @property
    def is_on(self) -> bool:
        """Whether the door is connected."""
        return self.coordinator.door.connected

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Reconnect to the door."""
        try:
            await self.coordinator.door.connect()
        except (CommandError, OSError, TimeoutError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
                translation_placeholders={
                    "host": self.coordinator.door.host,
                    "port": str(self.coordinator.door.port),
                },
            ) from err
        # Everything cached went stale while disconnected.
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disconnect, and stop the library reconnecting.

        `disconnect()` is documented as stopping automatic reconnection, so
        the door stays free for the phone app until the user turns this back
        on.
        """
        await self.coordinator.door.disconnect()
        self.coordinator.async_update_listeners()
