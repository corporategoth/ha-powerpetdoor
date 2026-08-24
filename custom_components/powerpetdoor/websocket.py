# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""WebSocket API backing the Power Pet Door Lovelace card.

This is the integration's only inbound surface. Home Assistant's own
schedule editor is bound to the core `schedule` domain's storage collection
and cannot be pointed at a device-backed schedule, so the card in `www/`
plus these three commands are how a user edits the door's schedule.

Every command is reachable by any logged-in Home Assistant user, so each
validates its payload with voluptuous and the mutating one requires admin.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from powerpetdoor import CommandError

from .const import (
    ATTR_SCHEDULE,
    DOMAIN,
    SCHEDULE_INSIDE,
    SCHEDULE_OUTSIDE,
    WS_SCHEDULE_GET,
    WS_SCHEDULE_LIST,
    WS_SCHEDULE_UPDATE,
)
from .coordinator import PowerPetDoorConfigEntry, PowerPetDoorCoordinator
from .schedule import SCHEDULE_PAYLOAD_SCHEMA, apply_schedule, to_ha_format

_LOGGER = logging.getLogger(__name__)

#: Set once per Home Assistant run. The commands are global, not per-entry,
#: so registering them again for a second door would raise.
_REGISTERED = f"{DOMAIN}_websocket_registered"


@callback
def async_register_websocket_api(hass: HomeAssistant) -> None:
    """Register the schedule commands, once per Home Assistant run."""
    if hass.data.get(_REGISTERED):
        return
    hass.data[_REGISTERED] = True
    websocket_api.async_register_command(hass, ws_list_schedules)
    websocket_api.async_register_command(hass, ws_get_schedule)
    websocket_api.async_register_command(hass, ws_update_schedule)


def _resolve(hass: HomeAssistant, entity_id: str) -> tuple[PowerPetDoorCoordinator, str] | None:
    """Find the coordinator and schedule kind behind a schedule entity_id.

    Resolved through the entity registry rather than by scanning entity
    objects: the registry is the only place that maps an entity_id back to
    the config entry that owns it, which is what makes this correct with
    more than one door configured.
    """
    registry = er.async_get(hass)
    entry = registry.async_get(entity_id)
    if entry is None or entry.platform != DOMAIN or entry.domain != "binary_sensor":
        return None

    # unique_id is "<host>:<port>-<kind>_schedule"; the kind is what we need.
    for kind in (SCHEDULE_INSIDE, SCHEDULE_OUTSIDE):
        if entry.unique_id.endswith(f"-{kind}_schedule"):
            break
    else:
        return None

    config_entry: PowerPetDoorConfigEntry | None = hass.config_entries.async_get_entry(
        entry.config_entry_id or ""
    )
    # `hasattr` is the whole check: Home Assistant assigns `runtime_data`
    # during setup and DELETES the attribute again on unload, so it is either
    # absent or a real coordinator - it is never None. Entity registry rows
    # outlive the entry that made them, which is why the absent case is
    # reachable at all: after a restart the rows exist before setup runs.
    if config_entry is None or not hasattr(config_entry, "runtime_data"):
        return None
    return config_entry.runtime_data, kind


def _payload(entity_id: str, coordinator: PowerPetDoorCoordinator, kind: str) -> dict[str, Any]:
    """Return the card's view of one schedule entity."""
    schedule = to_ha_format(coordinator.schedules, kind)
    return {
        "entity_id": entity_id,
        "kind": kind,
        "schedule": schedule,
        "schedule_count": sum(len(slots) for slots in schedule.values()),
        # The door's master switch. Without it the card cannot tell whether
        # the windows it is drawing are being enforced at all: with the
        # schedule engine off the door consults no window and both sensors
        # are live around the clock, so a grid of windows implies a
        # restriction that does not exist and an edit to it changes nothing.
        "timers_enabled": coordinator.door.auto,
    }


@websocket_api.websocket_command({vol.Required("type"): WS_SCHEDULE_LIST})
@callback
def ws_list_schedules(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """List every Power Pet Door schedule entity and its schedule."""
    registry = er.async_get(hass)
    results = []
    for entry in registry.entities.values():
        if entry.platform != DOMAIN or not entry.unique_id.endswith("_schedule"):
            continue
        resolved = _resolve(hass, entry.entity_id)
        if resolved is None:
            continue
        coordinator, kind = resolved
        results.append(_payload(entry.entity_id, coordinator, kind))
    connection.send_result(msg["id"], results)


@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_SCHEDULE_GET,
        vol.Required("entity_id"): str,
    }
)
@callback
def ws_get_schedule(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return one Power Pet Door schedule."""
    resolved = _resolve(hass, msg["entity_id"])
    if resolved is None:
        connection.send_error(
            msg["id"],
            websocket_api.const.ERR_NOT_FOUND,
            f"{msg['entity_id']} is not a Power Pet Door schedule entity",
        )
        return
    coordinator, kind = resolved
    connection.send_result(msg["id"], _payload(msg["entity_id"], coordinator, kind))


@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_SCHEDULE_UPDATE,
        vol.Required("entity_id"): str,
        vol.Required(ATTR_SCHEDULE): SCHEDULE_PAYLOAD_SCHEMA,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_update_schedule(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Replace the schedule for one sensor."""
    resolved = _resolve(hass, msg["entity_id"])
    if resolved is None:
        connection.send_error(
            msg["id"],
            websocket_api.const.ERR_NOT_FOUND,
            f"{msg['entity_id']} is not a Power Pet Door schedule entity",
        )
        return
    coordinator, kind = resolved

    try:
        await apply_schedule(coordinator, kind, msg[ATTR_SCHEDULE])
    except (CommandError, OSError, TimeoutError, ValueError) as err:
        _LOGGER.exception("Failed to update the %s schedule", kind)
        connection.send_error(msg["id"], "update_failed", str(err))
        return

    connection.send_result(msg["id"], _payload(msg["entity_id"], coordinator, kind))
