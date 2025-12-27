# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""WebSocket API for Power Pet Door schedules."""
from __future__ import annotations

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.components.schedule import DOMAIN as SCHEDULE_DOMAIN
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN, ATTR_SCHEDULE
from .schedule import PetDoorSchedule

import logging

_LOGGER = logging.getLogger(__name__)


async def async_setup_websocket_api(hass: HomeAssistant) -> None:
    """Set up the WebSocket API for Power Pet Door schedules."""
    websocket_api.async_register_command(hass, ws_list_schedules)
    websocket_api.async_register_command(hass, ws_get_schedule)
    websocket_api.async_register_command(hass, ws_update_schedule)
    _LOGGER.debug("Registered Power Pet Door WebSocket commands")


@websocket_api.websocket_command(
    {
        vol.Required("type"): "powerpetdoor/schedule/list",
    }
)
@callback
def ws_list_schedules(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Return a list of Power Pet Door schedules."""
    schedule_component = hass.data.get(SCHEDULE_DOMAIN)
    if not schedule_component:
        connection.send_result(msg["id"], [])
        return

    schedules = []
    for entity in schedule_component.entities:
        if isinstance(entity, PetDoorSchedule):
            # Get the structured schedule data from entity attributes
            attrs = entity.extra_state_attributes or {}
            schedule_data = attrs.get(ATTR_SCHEDULE, {})

            schedules.append({
                "id": entity.entity_id,
                "unique_id": entity.unique_id,
                "name": entity.name,
                "icon": entity.icon,
                "state": entity.state,
                "schedule": schedule_data,
                "schedule_entries": attrs.get("schedule_entries", []),
                "schedule_count": attrs.get("schedule_count", 0),
            })

    connection.send_result(msg["id"], schedules)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "powerpetdoor/schedule/get",
        vol.Required("entity_id"): str,
    }
)
@callback
def ws_get_schedule(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Return a specific Power Pet Door schedule."""
    entity_id = msg["entity_id"]
    schedule_component = hass.data.get(SCHEDULE_DOMAIN)

    if not schedule_component:
        connection.send_error(msg["id"], "not_found", "Schedule component not available")
        return

    for entity in schedule_component.entities:
        if entity.entity_id == entity_id and isinstance(entity, PetDoorSchedule):
            attrs = entity.extra_state_attributes or {}
            schedule_data = attrs.get(ATTR_SCHEDULE, {})

            connection.send_result(msg["id"], {
                "id": entity.entity_id,
                "unique_id": entity.unique_id,
                "name": entity.name,
                "icon": entity.icon,
                "state": entity.state,
                "schedule": schedule_data,
                "schedule_entries": attrs.get("schedule_entries", []),
                "schedule_count": attrs.get("schedule_count", 0),
            })
            return

    connection.send_error(msg["id"], "not_found", f"Schedule entity {entity_id} not found")


@websocket_api.websocket_command(
    {
        vol.Required("type"): "powerpetdoor/schedule/update",
        vol.Required("entity_id"): str,
        vol.Required("schedule"): dict,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_update_schedule(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Update a Power Pet Door schedule."""
    entity_id = msg["entity_id"]
    schedule_data = msg["schedule"]

    schedule_component = hass.data.get(SCHEDULE_DOMAIN)
    if not schedule_component:
        connection.send_error(msg["id"], "not_found", "Schedule component not available")
        return

    for entity in schedule_component.entities:
        if entity.entity_id == entity_id and isinstance(entity, PetDoorSchedule):
            try:
                # Convert schedule format to what async_update_config expects
                # The frontend sends: {"monday": [{"from": "06:00", "to": "20:00"}], ...}
                # async_update_config expects the same format with time objects
                from datetime import time as dt_time

                config = {}
                for day, time_slots in schedule_data.items():
                    if time_slots:
                        config[day] = []
                        for slot in time_slots:
                            from_parts = slot["from"].split(":")
                            to_parts = slot["to"].split(":")
                            config[day].append({
                                "from": dt_time(int(from_parts[0]), int(from_parts[1])),
                                "to": dt_time(int(to_parts[0]), int(to_parts[1])),
                            })

                await entity.async_update_config(config)

                # Return the updated schedule
                attrs = entity.extra_state_attributes or {}
                connection.send_result(msg["id"], {
                    "id": entity.entity_id,
                    "schedule": attrs.get(ATTR_SCHEDULE, {}),
                })
                return

            except Exception as e:
                _LOGGER.error("Failed to update schedule %s: %s", entity_id, e)
                connection.send_error(msg["id"], "update_failed", str(e))
                return

    connection.send_error(msg["id"], "not_found", f"Schedule entity {entity_id} not found")
