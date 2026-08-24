# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""Binary sensor entities for the Power Pet Door."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import voluptuous as vol
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import (
    HomeAssistantError,
    ServiceNotSupported,
    Unauthorized,
)
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util import dt as dt_util
from powerpetdoor import CommandError, PowerPetDoor

from .const import (
    ATTR_NEXT_EVENT,
    ATTR_SCHEDULE,
    ATTR_SCHEDULE_COUNT,
    ATTR_SCHEDULE_ENTRIES,
    DOMAIN,
    SCHEDULE_INSIDE,
    SCHEDULE_OUTSIDE,
    SERVICE_SET_SCHEDULE,
)
from .coordinator import PowerPetDoorConfigEntry, PowerPetDoorCoordinator
from .entity import PowerPetDoorEntity, PowerPetDoorPoweredEntity
from .schedule import (
    SCHEDULE_PAYLOAD_SCHEMA,
    apply_schedule,
    is_active,
    next_event,
    summarise,
    to_ha_format,
)

#: 1, not 0. `set_schedule` is a read-modify-write over a table the door
#: holds ONCE for both sensors, so it cannot run concurrently with itself.
#: With 0 Home Assistant gives the platform no semaphore and
#: `entity_service_call` gathers the calls: one action naming both schedule
#: entities - or naming the DEVICE, which is what the visual action editor
#: produces - had both coroutines rebuild the other kind from the same
#: pre-edit table, and the last writer resurrected the other's old windows.
#: One of the two writes vanished, the action reported success, and nothing
#: was logged.
PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class PowerPetDoorBinarySensorDescription(BinarySensorEntityDescription):
    """Describes one Power Pet Door binary sensor."""

    value_fn: Callable[[PowerPetDoor], bool]


BINARY_SENSORS: tuple[PowerPetDoorBinarySensorDescription, ...] = (
    PowerPetDoorBinarySensorDescription(
        key="mains_power",
        translation_key="mains_power",
        device_class=BinarySensorDeviceClass.PLUG,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda door: door.battery.ac_present,
    ),
    PowerPetDoorBinarySensorDescription(
        key="battery_charging",
        translation_key="battery_charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda door: door.battery.charging,
    ),
    PowerPetDoorBinarySensorDescription(
        key="remote_id",
        translation_key="remote_id",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda door: door.has_remote_id,
    ),
    PowerPetDoorBinarySensorDescription(
        key="remote_key",
        translation_key="remote_key",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda door: door.has_remote_key,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowerPetDoorConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Power Pet Door binary sensors."""
    coordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = [
        PowerPetDoorBinarySensor(coordinator, description) for description in BINARY_SENSORS
    ]
    entities.extend(
        PowerPetDoorScheduleSensor(coordinator, kind)
        for kind in (SCHEDULE_INSIDE, SCHEDULE_OUTSIDE)
    )
    async_add_entities(entities)

    # An entity service, not a domain one: it targets a specific schedule
    # entity, which is what keeps it correct when two doors are configured.
    # Validated with the SAME schema the WebSocket command uses. Taking a
    # bare `dict` here meant an automation with a malformed payload got a
    # raw KeyError or TypeError out of the write path, while the card got a
    # clean rejection for the identical input.
    #
    # A callable rather than a method name, because Home Assistant offers no
    # way to restrict an entity service to a subset of a platform's
    # entities: `services.yaml` can only target `domain: binary_sensor`, so
    # the action picker offers all six of ours and a device-wide target
    # sweeps them. Dispatching by name would then hit `getattr` on an
    # entity that has no such method and raise AttributeError at the user.
    entity_platform.async_get_current_platform().async_register_entity_service(
        SERVICE_SET_SCHEDULE,
        {vol.Required(ATTR_SCHEDULE): SCHEDULE_PAYLOAD_SCHEMA},
        _async_set_schedule_service,
    )


class PowerPetDoorBinarySensor(PowerPetDoorEntity, BinarySensorEntity):
    """A boolean read from the door."""

    entity_description: PowerPetDoorBinarySensorDescription

    def __init__(
        self,
        coordinator: PowerPetDoorCoordinator,
        description: PowerPetDoorBinarySensorDescription,
    ) -> None:
        """Initialise the binary sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool:
        """Return the current value."""
        return self.entity_description.value_fn(self.coordinator.door)


class PowerPetDoorScheduleSensor(PowerPetDoorPoweredEntity, BinarySensorEntity):
    """Whether the door's schedule currently permits one sensor.

    This is the replacement for the core `schedule` helper entities the
    first version of this integration tried to hijack. It reports the same
    thing HA's Schedule entity does - on while a window is open - and
    carries the whole schedule in its attributes, in HA's own format, so the
    Lovelace card can render and edit it through the WebSocket API.
    """

    def __init__(self, coordinator: PowerPetDoorCoordinator, kind: str) -> None:
        """Initialise the schedule sensor for the inside or outside sensor."""
        super().__init__(coordinator, f"{kind}_schedule")
        self._kind = kind
        self._unsub_next: Callable[[], None] | None = None

    @property
    def is_on(self) -> bool:
        """Whether the schedule currently permits this sensor."""
        if not self.coordinator.door.auto:
            # The master switch, checked first exactly as the door checks it
            # (`is_sensor_allowed_by_schedule`: `if not self.auto: return
            # True`). With the schedule engine off the door consults no
            # window at all, so reporting one closed would contradict the
            # switch sitting next to this sensor - which is literally named
            # "Schedule enabled" - while the pet walked through.
            return True
        return is_active(self.coordinator.schedules, self._kind, dt_util.now())

    def _next_event(self) -> datetime | None:
        """When this sensor next changes, or None if it never does.

        None while the schedule engine is off: nothing is being enforced, so
        no window edge changes anything until the user turns it back on -
        and that arrives as a settings push, which re-arms the timer.
        """
        if not self.coordinator.door.auto:
            return None
        return next_event(self.coordinator.schedules, self._kind, dt_util.now())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The whole schedule, plus when it next changes."""
        upcoming = self._next_event()
        schedule = to_ha_format(self.coordinator.schedules, self._kind)
        return {
            ATTR_SCHEDULE: schedule,
            ATTR_SCHEDULE_ENTRIES: summarise(self.coordinator.schedules, self._kind),
            ATTR_SCHEDULE_COUNT: sum(len(slots) for slots in schedule.values()),
            ATTR_NEXT_EVENT: upcoming.isoformat() if upcoming else None,
        }

    async def async_added_to_hass(self) -> None:
        """Start tracking the next schedule edge."""
        await super().async_added_to_hass()
        self._schedule_next_update()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Re-arm the timer whenever the schedule itself changes."""
        self._schedule_next_update()
        super()._handle_coordinator_update()

    @callback
    def _schedule_next_update(self) -> None:
        """Wake up exactly when this sensor's state next changes.

        Without this the sensor would only move when something else prodded
        the coordinator, so a window opening at 06:00 would be reported
        whenever the next poll happened to land - up to the refresh interval
        late. Tracking the computed edge makes the transition punctual and
        costs one timer.
        """
        self._cancel_next_update()
        upcoming = self._next_event()
        if upcoming is None:
            return
        self._unsub_next = async_track_point_in_utc_time(
            self.hass, self._handle_edge, dt_util.as_utc(upcoming)
        )

    @callback
    def _cancel_next_update(self) -> None:
        if self._unsub_next is not None:
            self._unsub_next()
            self._unsub_next = None

    @callback
    def _handle_edge(self, _now: Any) -> None:
        """Publish the new state and re-arm, now the tracked edge has arrived."""
        self._unsub_next = None
        self._schedule_next_update()
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        """Drop the timer so a removed entity cannot keep firing."""
        self._cancel_next_update()
        await super().async_will_remove_from_hass()

    async def async_set_schedule(self, schedule: dict[str, Any]) -> None:
        """Replace this sensor's schedule from an automation.

        Same payload and same code path as the WebSocket command the card
        uses - `apply_schedule` is shared - so the two can never drift into
        doing different things to the door.
        """
        try:
            await apply_schedule(self.coordinator, self._kind, schedule)
        except (CommandError, OSError, TimeoutError, ValueError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="schedule_update_failed",
                translation_placeholders={"error": str(err)},
            ) from err


async def _async_set_schedule_service(entity: BinarySensorEntity, call: ServiceCall) -> None:
    """Route `powerpetdoor.set_schedule` to a schedule entity.

    Home Assistant matches entity services by platform, not by class, so a
    user targeting the device - or picking any of this integration's other
    binary sensors - lands here too. Reject those with the standard
    "action not supported" error rather than letting `getattr` raise
    AttributeError out of the service call.
    """
    if not isinstance(entity, PowerPetDoorScheduleSensor):
        # Home Assistant's own exception for this, so the user sees the
        # same wording they would from any other integration, already
        # translated by core.
        raise ServiceNotSupported(DOMAIN, SERVICE_SET_SCHEDULE, entity.entity_id)

    await _async_check_admin(call)
    await entity.async_set_schedule(call.data[ATTR_SCHEDULE])


async def _async_check_admin(call: ServiceCall) -> None:
    """Refuse a schedule rewrite from a non-admin.

    The WebSocket command the card uses is `@require_admin`, but an entity
    service is not: Home Assistant's default policy for an ordinary
    non-admin user is `{"entities": True}`, i.e. full entity control. So
    without this the exact user `ws_update_schedule` refuses could call the
    action instead and rewrite the door's schedule table - and because
    `apply_schedule` diffs against the current table, that DELETES rows an
    admin created - by a user the card itself renders read-only, with no
    editing controls at all.

    A call with no user is a script, an automation or a blueprint, which is
    the action's whole reason to exist; those are allowed through. That is
    the same rule `websocket_api.require_admin` applies.
    """
    if call.context.user_id is None:
        return
    user = await call.hass.auth.async_get_user(call.context.user_id)
    if user is None or not user.is_admin:
        raise Unauthorized(context=call.context)
