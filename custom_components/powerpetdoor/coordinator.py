# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""Coordinator that owns the connection to one Power Pet Door."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_TIMEOUT
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from powerpetdoor import CommandError, PowerPetDoor, Schedule

from .const import (
    CONF_KEEP_ALIVE,
    CONF_RECONNECT,
    CONF_REFRESH,
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_KEEP_ALIVE_TIMEOUT,
    DEFAULT_RECONNECT_TIMEOUT,
    DEFAULT_REFRESH_TIMEOUT,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

#: `ConfigEntry` carrying our runtime data. Platinum's `runtime-data` rule:
#: per-entry state lives on the entry, typed, never in `hass.data[DOMAIN]`.
type PowerPetDoorConfigEntry = ConfigEntry[PowerPetDoorCoordinator]


class PowerPetDoorCoordinator(DataUpdateCoordinator[None]):
    """Owns one `PowerPetDoor` and tells entities when it changed.

    The coordinator is `DataUpdateCoordinator[None]` on purpose. The library
    facade already caches every value and exposes it as a property, so there
    is nothing for `_async_update_data` to *return* - copying that cache into
    a second dict would mean two sources of truth and a class of bug where
    an entity reads a stale copy of something the door already corrected.
    Entities read `coordinator.door.<property>` directly; this class exists
    to own the connection lifecycle and to convert the facade's callbacks
    into `async_update_listeners()`.

    The door is `local_push`: it sends state changes unprompted. The polling
    interval is therefore a safety net for missed pushes, not the primary
    update path.
    """

    config_entry: PowerPetDoorConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: PowerPetDoorConfigEntry,
    ) -> None:
        """Initialise the coordinator and the door facade."""
        self.door = PowerPetDoor(
            host=entry.data[CONF_HOST],
            port=entry.data[CONF_PORT],
            # `or DEFAULT` rather than `.get(key, DEFAULT)`: an options
            # flow that stored 0 means "no timeout" to a user but would be
            # an immediately-expiring timeout to the library, and the
            # facade's parameter is not Optional.
            timeout=entry.options.get(CONF_TIMEOUT) or DEFAULT_CONNECT_TIMEOUT,
            reconnect=entry.options.get(CONF_RECONNECT, DEFAULT_RECONNECT_TIMEOUT),
            keepalive=entry.options.get(CONF_KEEP_ALIVE, DEFAULT_KEEP_ALIVE_TIMEOUT),
            loop=hass.loop,
        )

        #: Serialises the schedule read-modify-write. `PARALLEL_UPDATES` on
        #: the binary_sensor platform covers two entity-service calls racing
        #: each other, but not the OTHER caller: the Lovelace card writes
        #: through the WebSocket API, so a card save landing between an
        #: automation's read and its write still loses one of them. The door
        #: holds one table for both sensors and takes one connection, so
        #: there is nothing to gain from overlapping these anyway.
        #:
        #: Per coordinator, so two doors never wait on each other.
        self.schedule_lock = asyncio.Lock()

        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=entry.title,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_REFRESH, DEFAULT_REFRESH_TIMEOUT)
            ),
        )

        # Every one of these is a *push* from the door. Without them the
        # integration would be local_polling wearing a local_push label.
        self.door.on_status_change(self._handle_push)
        self.door.on_settings_change(self._handle_push)
        self.door.on_schedule_change(self._handle_push)
        self.door.on_connect(self._handle_reconnect)
        self.door.on_disconnect(self._handle_connectivity)

    # -- lifecycle ---------------------------------------------------------

    async def async_connect(self) -> None:
        """Connect, or raise `ConfigEntryNotReady` so HA retries.

        Platinum's `test-before-setup`. A door that is unplugged, asleep or
        on a different address must leave the entry in a retrying state with
        a message, not a half-set-up entry full of unavailable entities.
        """
        try:
            await self.door.connect()
        except (CommandError, OSError, TimeoutError) as err:
            raise ConfigEntryNotReady(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
                translation_placeholders={
                    "host": self.door.host,
                    "port": str(self.door.port),
                },
            ) from err

    async def async_shutdown(self) -> None:
        """Disconnect and stop reconnecting."""
        await super().async_shutdown()
        await self.door.disconnect()

    # -- updates -----------------------------------------------------------

    async def _async_update_data(self) -> None:
        """Refresh everything the door will not push on its own.

        Returns nothing: see the class docstring. Entities read the facade's
        cache, which `refresh()` has just updated in place.
        """
        if not self.door.connected:
            # Reconnection is the library's job and it is already trying.
            # Raising here marks entities unavailable, which is exactly the
            # truth, without fighting the library's backoff.
            raise UpdateFailed(f"Not connected to {self.door.host}:{self.door.port}")
        try:
            # Before the bulk refresh, one call that actually raises when the
            # door stops answering. `refresh()` gathers with
            # return_exceptions=True and only logs, so on its own it can
            # never fail - which left the UpdateFailed arm below unreachable
            # and let entities keep serving a stale cache as though current.
            await self.door.refresh_status()
            await self.door.refresh()
        except (CommandError, OSError, TimeoutError) as err:
            raise UpdateFailed(str(err)) from err

    @callback
    def _handle_push(self, _value: object = None) -> None:
        """Re-read the facade after a push from the door.

        One handler for status, settings and schedules because the facade
        has already applied the change to its cache by the time this runs -
        all that is left is to tell entities to re-read it. The parameter is
        ignored for the same reason.
        """
        self.async_update_listeners()

    @callback
    def _handle_connectivity(self) -> None:
        """Refresh every entity's availability after a disconnect."""
        self.async_update_listeners()

    @callback
    def _handle_reconnect(self) -> None:
        """Mark the coordinator healthy again the moment the door is back.

        `available` is `door.connected AND last_update_success`, and any
        outage lasting longer than the refresh interval guarantees at least
        one failed poll - which sets `last_update_success` False. Telling
        listeners to re-read is not enough, because nothing has cleared that
        flag: every entity stayed `unavailable` until the NEXT scheduled
        poll, up to a full refresh interval after Home Assistant was
        demonstrably talking to the door again. That is 300 seconds by
        default and the options flow permits 86400.

        `async_set_updated_data` clears the flag and reschedules the poll.
        Passing None is right for this coordinator: it is
        `DataUpdateCoordinator[None]` because the library facade owns the
        cache and entities read it directly - and the library awaits
        `refresh()` before firing this callback, so that cache is already
        current.
        """
        self.async_set_updated_data(None)

    # -- helpers used by more than one platform ----------------------------

    @property
    def schedules(self) -> list[Schedule]:
        """Schedules currently cached by the facade."""
        return self.door.schedules

    @property
    def device_identifier(self) -> str:
        """Stable per-door identifier used for unique_ids and the device.

        host:port, matching what previous versions used. Changing it would
        orphan every existing entity in the registry and lose the user's
        history, so it is fixed by compatibility rather than chosen.
        """
        return f"{self.door.host}:{self.door.port}"

    async def async_refresh_diagnostic_data(self) -> None:
        """Fetch the values `refresh()` deliberately leaves out.

        The door's clock and its remote pairing are excluded from the bulk
        refresh by the library, with reasons that hold: the clock "goes
        stale the moment it arrives", the pairing is static. Neither is
        worth a polled entity, so they are read here - on demand, when a
        diagnostics download is actually being taken.

        Failures are swallowed: a diagnostics download is what a user
        produces when something is already wrong, and it must not be the
        one thing that also fails. A door that cannot answer simply leaves
        the previous values in place.
        """
        for refresh in (self.door.refresh_time, self.door.refresh_remote_info):
            try:
                await refresh()
            except (CommandError, OSError, TimeoutError) as err:
                _LOGGER.debug("Diagnostic refresh %s failed: %s", refresh.__name__, err)

    def diagnostics(self) -> dict[str, Any]:
        """Everything known about the door, for the diagnostics download."""
        battery = self.door.battery
        return {
            "connected": self.door.connected,
            # `PowerPetDoor.latency` is SECONDS; this key says milliseconds.
            # Same unit confusion the latency sensor had, in a third place.
            "latency_ms": None if self.door.latency is None else self.door.latency * 1000,
            "status": self.door.status.value,
            "position": self.door.position,
            "firmware_version": self.door.firmware_version,
            "hardware_version": self.door.hardware_version,
            "hardware_info": self.door.hardware_info,
            "device_time": self.door.device_time,
            "timezone": self.door.timezone,
            "settings": {
                "power": self.door.power,
                "inside_sensor": self.door.inside_sensor,
                "outside_sensor": self.door.outside_sensor,
                "auto": self.door.auto,
                "safety_lock": self.door.safety_lock,
                "autoretract": self.door.autoretract,
                "pet_proximity_keep_open": self.door.pet_proximity_keep_open,
                "hold_time": self.door.hold_time,
                "sensor_trigger_voltage": self.door.sensor_trigger_voltage,
                "sleep_sensor_trigger_voltage": self.door.sleep_sensor_trigger_voltage,
            },
            "battery": {
                "percent": battery.percent,
                "present": battery.present,
                "ac_present": battery.ac_present,
                "charging": battery.charging,
                "discharging": battery.discharging,
            },
            "stats": {
                "total_open_cycles": self.door.total_open_cycles,
                "total_auto_retracts": self.door.total_auto_retracts,
            },
            "remote": {
                "has_remote_id": self.door.has_remote_id,
                "has_remote_key": self.door.has_remote_key,
            },
            "schedules": [schedule.to_dict() for schedule in self.door.schedules],
        }
