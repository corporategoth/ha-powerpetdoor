from __future__ import annotations

from datetime import datetime, time, timezone, timedelta
from copy import deepcopy

import voluptuous as vol

from homeassistant.core import HomeAssistant, callback
from homeassistant.const import EntityCategory, ATTR_ENTITY_ID
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, CoordinatorEntity
from homeassistant.config_entries import ConfigEntry, SOURCE_IMPORT
from homeassistant.components.schedule import Schedule, WEEKDAY_TO_CONF, CONF_FROM, CONF_TO, ENTITY_SCHEMA, DOMAIN as SCHEDULE_DOMAIN
import homeassistant.helpers.config_validation as cv
from .client import PowerPetDoorClient

from .const import (
    DOMAIN,
    CONF_HOST,
    CONF_PORT,
    CONF_NAME,
    CONF_ICON,
    CONF_ID,
    CONF_REFRESH,
    CONFIG,
    STATE_LAST_CHANGE,
    FIELD_POWER,
    FIELD_INSIDE,
    FIELD_OUTSIDE,
    FIELD_INDEX,
    FIELD_ENABLED,
    FIELD_DAYSOFWEEK,
    FIELD_INSIDE_PREFIX,
    FIELD_OUTSIDE_PREFIX,
    FIELD_START_TIME_SUFFIX,
    FIELD_END_TIME_SUFFIX,
    FIELD_HOUR,
    FIELD_MINUTE,
    CMD_GET_SCHEDULE_LIST,
    CMD_DELETE_SCHEDULE,
    CMD_GET_SCHEDULE,
    CMD_SET_SCHEDULE,
    SERVICE_UPDATE_SCHEDULE,
    ATTR_SCHEDULE,
    ATTR_SCHEDULE_ENTRIES,
    ATTR_SCHEDULE_COUNT,
)

import logging

_LOGGER = logging.getLogger(__name__)

SCHEDULES = {
    "inside": {
        "field": FIELD_INSIDE,
        "prefix": FIELD_INSIDE_PREFIX,
        "icon": "mdi:home-clock",
        "category": EntityCategory.CONFIG,
        "disabled": True,
    },
    "outside": {
        "field": FIELD_OUTSIDE,
        "prefix": FIELD_OUTSIDE_PREFIX,
        "icon": "mdi:sun-clock",
        "category": EntityCategory.CONFIG,
        "disabled": True,
    },
}


def week_0_mon_to_sun(val: int) -> int:
    return (val + 8) % 7


def week_0_sun_to_mon(val: int) -> int:
    return (val + 6) % 7


def validate_schedule_entry(sched: dict) -> bool:
    """Validate a schedule entry has required fields and valid data."""
    try:
        # Check required fields exist
        if FIELD_INDEX not in sched:
            _LOGGER.debug("Schedule entry missing index field: %s", sched)
            return False

        if FIELD_DAYSOFWEEK not in sched:
            _LOGGER.debug("Schedule entry missing daysOfWeek field: %s", sched)
            return False

        # Validate daysOfWeek is a list of 7 elements
        if not isinstance(sched[FIELD_DAYSOFWEEK], list) or len(sched[FIELD_DAYSOFWEEK]) != 7:
            _LOGGER.debug("Schedule entry has invalid daysOfWeek format: %s", sched[FIELD_DAYSOFWEEK])
            return False

        # Validate time fields if inside or outside is enabled
        if sched.get(FIELD_INSIDE, False):
            in_start_key = FIELD_INSIDE_PREFIX + FIELD_START_TIME_SUFFIX
            in_end_key = FIELD_INSIDE_PREFIX + FIELD_END_TIME_SUFFIX
            if in_start_key not in sched or in_end_key not in sched:
                _LOGGER.debug("Schedule entry missing inside time fields: %s", sched)
                return False
            if FIELD_HOUR not in sched[in_start_key] or FIELD_MINUTE not in sched[in_start_key]:
                _LOGGER.debug("Schedule entry has invalid inside start time: %s", sched[in_start_key])
                return False
            if FIELD_HOUR not in sched[in_end_key] or FIELD_MINUTE not in sched[in_end_key]:
                _LOGGER.debug("Schedule entry has invalid inside end time: %s", sched[in_end_key])
                return False

        if sched.get(FIELD_OUTSIDE, False):
            out_start_key = FIELD_OUTSIDE_PREFIX + FIELD_START_TIME_SUFFIX
            out_end_key = FIELD_OUTSIDE_PREFIX + FIELD_END_TIME_SUFFIX
            if out_start_key not in sched or out_end_key not in sched:
                _LOGGER.debug("Schedule entry missing outside time fields: %s", sched)
                return False
            if FIELD_HOUR not in sched[out_start_key] or FIELD_MINUTE not in sched[out_start_key]:
                _LOGGER.debug("Schedule entry has invalid outside start time: %s", sched[out_start_key])
                return False
            if FIELD_HOUR not in sched[out_end_key] or FIELD_MINUTE not in sched[out_end_key]:
                _LOGGER.debug("Schedule entry has invalid outside end time: %s", sched[out_end_key])
                return False

        return True
    except Exception as e:
        _LOGGER.error("Error validating schedule entry: %s", e, exc_info=True)
        return False


schedule_template = {
    FIELD_INDEX: 0,
    FIELD_DAYSOFWEEK: [0, 0, 0, 0, 0, 0, 0],
    FIELD_INSIDE: False,
    FIELD_OUTSIDE: False,
    FIELD_ENABLED: True,
    FIELD_INSIDE_PREFIX + FIELD_START_TIME_SUFFIX: {FIELD_HOUR: 0, FIELD_MINUTE: 0},
    FIELD_INSIDE_PREFIX + FIELD_END_TIME_SUFFIX: {FIELD_HOUR: 0, FIELD_MINUTE: 0},
    FIELD_OUTSIDE_PREFIX + FIELD_START_TIME_SUFFIX: {FIELD_HOUR: 0, FIELD_MINUTE: 0},
    FIELD_OUTSIDE_PREFIX + FIELD_END_TIME_SUFFIX: {FIELD_HOUR: 0, FIELD_MINUTE: 0},
}

def compress_schedule(schedule: dict) -> dict:
    """ Take the schedule and reduce it to as few entries as possible. """
    expanded_sched = {
        FIELD_INSIDE: {},
        FIELD_OUTSIDE: {},
    }

    # Step 1 .. expand
    for sched in schedule:
        in_start = time(sched[FIELD_INSIDE_PREFIX + FIELD_START_TIME_SUFFIX][FIELD_HOUR],
                        sched[FIELD_INSIDE_PREFIX + FIELD_START_TIME_SUFFIX][FIELD_MINUTE])
        in_end = time(sched[FIELD_INSIDE_PREFIX + FIELD_END_TIME_SUFFIX][FIELD_HOUR],
                      sched[FIELD_INSIDE_PREFIX + FIELD_END_TIME_SUFFIX][FIELD_MINUTE])
        if in_end < in_start:
            in_start, in_end = in_end, in_start
        out_start = time(sched[FIELD_OUTSIDE_PREFIX + FIELD_START_TIME_SUFFIX][FIELD_HOUR],
                         sched[FIELD_OUTSIDE_PREFIX + FIELD_START_TIME_SUFFIX][FIELD_MINUTE])
        out_end = time(sched[FIELD_OUTSIDE_PREFIX + FIELD_END_TIME_SUFFIX][FIELD_HOUR],
                       sched[FIELD_OUTSIDE_PREFIX + FIELD_END_TIME_SUFFIX][FIELD_MINUTE])
        if out_end < out_start:
            out_start, out_end = out_end, out_start

        for day in range(len(sched[FIELD_DAYSOFWEEK])):
            if sched[FIELD_DAYSOFWEEK][day]:
                if sched[FIELD_INSIDE]:
                    daysched = expanded_sched[FIELD_INSIDE].setdefault(day, [])
                    daysched.append({"start": in_start, "end": in_end})
                if sched[FIELD_OUTSIDE]:
                    daysched = expanded_sched[FIELD_OUTSIDE].setdefault(day, [])
                    daysched.append({"start": out_start, "end": out_end})

    # Step 2 .. Combine adjacent or overlapping
    def combine_overlapping(xsched: dict) -> None:
        for daysched in xsched.values():
            daysched.sort(key=lambda d: d["start"])

            i=0
            while i < len(daysched) - 1:
                if daysched[i]["end"] >= daysched[i + 1]["start"]:
                    if daysched[i]["end"] < daysched[i + 1]["end"]:
                        daysched[i]["end"] = daysched[i + 1]["end"]
                    del daysched[i + 1]
                else:
                    i = i + 1

    combine_overlapping(expanded_sched[FIELD_INSIDE])
    combine_overlapping(expanded_sched[FIELD_OUTSIDE])

    # Step 3 .. Combine days of week
    def collapse_split_field(xsched: dict) -> list:
        out = []
        for day, daysched in xsched.items():
            for sched in daysched:
                found = False
                for ent in out:
                    if ent["start"] == sched["start"] and ent["end"] == sched["end"]:
                        ent[FIELD_DAYSOFWEEK][day] = 1
                        found = True
                        break
                if not found:
                    ent = {
                        "start": sched["start"],
                        "end": sched["end"],
                        FIELD_DAYSOFWEEK: [0, 0, 0, 0, 0, 0, 0]
                    }
                    ent[FIELD_DAYSOFWEEK][day] = 1
                    out.append(ent)
        return out

    split_sched = {
        FIELD_INSIDE: collapse_split_field(expanded_sched[FIELD_INSIDE]),
        FIELD_OUTSIDE: collapse_split_field(expanded_sched[FIELD_OUTSIDE]),
    }

    # Step 4 .. Combine Inside & Outside entries
    final_sched = []
    for sched in split_sched[FIELD_INSIDE]:
        ent = {
            FIELD_INSIDE: True,
            FIELD_OUTSIDE: False,
            FIELD_DAYSOFWEEK: sched[FIELD_DAYSOFWEEK],
            "start": sched["start"],
            "end": sched["end"],
        }
        final_sched.append(ent)
    for sched in split_sched[FIELD_OUTSIDE]:
        found = False
        for ent in final_sched:
            if (ent["start"] == sched["start"] and
                    ent["end"] == sched["end"] and
                    ent[FIELD_DAYSOFWEEK] == sched[FIELD_DAYSOFWEEK]):
                ent[FIELD_OUTSIDE] = True
                found = True
                break
        if not found:
            ent = {
                FIELD_INSIDE: False,
                FIELD_OUTSIDE: True,
                FIELD_DAYSOFWEEK: sched[FIELD_DAYSOFWEEK],
                "start": sched["start"],
                "end": sched["end"],
            }
            final_sched.append(ent)

    # Step 5, make template rows
    out = []
    index = 0
    for sched in final_sched:
        ent = deepcopy(schedule_template)
        ent[FIELD_INDEX] = index
        ent[FIELD_DAYSOFWEEK] = sched[FIELD_DAYSOFWEEK]
        if sched[FIELD_INSIDE]:
            ent[FIELD_INSIDE] = True
            ent[FIELD_INSIDE_PREFIX + FIELD_START_TIME_SUFFIX][FIELD_HOUR] = sched["start"].hour
            ent[FIELD_INSIDE_PREFIX + FIELD_START_TIME_SUFFIX][FIELD_MINUTE] = sched["start"].minute
            ent[FIELD_INSIDE_PREFIX + FIELD_END_TIME_SUFFIX][FIELD_HOUR] = sched["end"].hour
            ent[FIELD_INSIDE_PREFIX + FIELD_END_TIME_SUFFIX][FIELD_MINUTE] = sched["end"].minute
        if sched[FIELD_OUTSIDE]:
            ent[FIELD_OUTSIDE] = True
            ent[FIELD_OUTSIDE_PREFIX + FIELD_START_TIME_SUFFIX][FIELD_HOUR] = sched["start"].hour
            ent[FIELD_OUTSIDE_PREFIX + FIELD_START_TIME_SUFFIX][FIELD_MINUTE] = sched["start"].minute
            ent[FIELD_OUTSIDE_PREFIX + FIELD_END_TIME_SUFFIX][FIELD_HOUR] = sched["end"].hour
            ent[FIELD_OUTSIDE_PREFIX + FIELD_END_TIME_SUFFIX][FIELD_MINUTE] = sched["end"].minute
        out.append(ent)
        index += 1

    return out


def schedule_entry_content_key(entry: dict) -> tuple:
    """Create a hashable key representing schedule entry content (ignoring index).

    This allows comparing entries by their actual content rather than their index,
    which is important for incremental sync since compression may reassign indices.
    """
    # Extract time values
    in_start = (entry.get(FIELD_INSIDE_PREFIX + FIELD_START_TIME_SUFFIX, {}).get(FIELD_HOUR, 0),
                entry.get(FIELD_INSIDE_PREFIX + FIELD_START_TIME_SUFFIX, {}).get(FIELD_MINUTE, 0))
    in_end = (entry.get(FIELD_INSIDE_PREFIX + FIELD_END_TIME_SUFFIX, {}).get(FIELD_HOUR, 0),
              entry.get(FIELD_INSIDE_PREFIX + FIELD_END_TIME_SUFFIX, {}).get(FIELD_MINUTE, 0))
    out_start = (entry.get(FIELD_OUTSIDE_PREFIX + FIELD_START_TIME_SUFFIX, {}).get(FIELD_HOUR, 0),
                 entry.get(FIELD_OUTSIDE_PREFIX + FIELD_START_TIME_SUFFIX, {}).get(FIELD_MINUTE, 0))
    out_end = (entry.get(FIELD_OUTSIDE_PREFIX + FIELD_END_TIME_SUFFIX, {}).get(FIELD_HOUR, 0),
               entry.get(FIELD_OUTSIDE_PREFIX + FIELD_END_TIME_SUFFIX, {}).get(FIELD_MINUTE, 0))

    return (
        tuple(entry.get(FIELD_DAYSOFWEEK, [0] * 7)),
        entry.get(FIELD_INSIDE, False),
        entry.get(FIELD_OUTSIDE, False),
        entry.get(FIELD_ENABLED, True),
        in_start, in_end,
        out_start, out_end,
    )


def compute_schedule_diff(current_schedule: list, new_schedule: list) -> tuple[list, list]:
    """Compare current and new schedules to determine what needs to change.

    Returns:
        (entries_to_delete, entries_to_add) where:
        - entries_to_delete: list of indices to delete from device
        - entries_to_add: list of new schedule entries to add
    """
    # Build lookup of current entries by content key
    current_by_content = {}
    for entry in current_schedule:
        key = schedule_entry_content_key(entry)
        current_by_content[key] = entry

    # Build lookup of new entries by content key
    new_by_content = {}
    for entry in new_schedule:
        key = schedule_entry_content_key(entry)
        new_by_content[key] = entry

    # Find entries to delete (in current but not in new)
    entries_to_delete = []
    for key, entry in current_by_content.items():
        if key not in new_by_content:
            entries_to_delete.append(entry[FIELD_INDEX])

    # Find entries to add (in new but not in current)
    entries_to_add = []
    for key, entry in new_by_content.items():
        if key not in current_by_content:
            entries_to_add.append(entry)

    return (entries_to_delete, entries_to_add)


class PetDoorSchedule(CoordinatorEntity, Schedule):
    def __init__(self,
                 client: PowerPetDoorClient,
                 name: str,
                 schedule: dict,
                 coordinator: DataUpdateCoordinator,
                 device: DeviceInfo | None = None) -> None:
        conf = {
            CONF_NAME: name,
            CONF_ICON: schedule["icon"],
            CONF_ID: f"{client.host}:{client.port}-schedule-{schedule['field']}",
        }
        CoordinatorEntity.__init__(self, coordinator)
        Schedule.__init__(self, config=conf, editable=True)
        self.client = client
        self.schedule = schedule

        self.last_change = None
        self.power = True

        if "category" in schedule:
            self._attr_entity_category = schedule["category"]
        if "disabled" in schedule:
            self._attr_entity_registry_enabled_default = not schedule["disabled"]
        self._attr_device_info = device

        client.add_listener(name=self.unique_id, sensor_update={FIELD_POWER: self.handle_power_update})

    @property
    def available(self) -> bool:
        return (self.client.available and super().available and self.power)

    @property
    def extra_state_attributes(self) -> dict | None:
        rv = {}
        if self.last_change:
            rv[STATE_LAST_CHANGE] = self.last_change.isoformat()

        if not self.coordinator.data:
            return rv

        # Build structured schedule data for UI editing (HA format)
        # Format: { "monday": [{"from": "06:00", "to": "20:00"}, ...], ... }
        day_names_ha = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]
        day_names_short = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        structured_schedule = {day: [] for day in day_names_ha}
        schedule_summary = []

        for sched in self.coordinator.data:
            # Filter out disabled entries
            if not sched.get(FIELD_ENABLED, True):
                continue

            # Only process entries for this schedule type (inside or outside)
            if not sched.get(self.schedule["field"], False):
                continue

            try:
                start_key = self.schedule["prefix"] + FIELD_START_TIME_SUFFIX
                end_key = self.schedule["prefix"] + FIELD_END_TIME_SUFFIX

                if start_key not in sched or end_key not in sched:
                    continue

                start_hour = sched[start_key].get(FIELD_HOUR, 0)
                start_min = sched[start_key].get(FIELD_MINUTE, 0)
                end_hour = sched[end_key].get(FIELD_HOUR, 0)
                end_min = sched[end_key].get(FIELD_MINUTE, 0)

                start_time = f"{start_hour:02d}:{start_min:02d}"
                end_time = f"{end_hour:02d}:{end_min:02d}"
                time_entry = {"from": start_time, "to": end_time}

                # Get days of week and add to structured schedule
                active_days = []
                for i, enabled in enumerate(sched.get(FIELD_DAYSOFWEEK, [])):
                    if enabled:
                        structured_schedule[day_names_ha[i]].append(time_entry.copy())
                        active_days.append(day_names_short[i])

                # Build human-readable summary
                if active_days:
                    schedule_summary.append(f"{', '.join(active_days)}: {start_time}-{end_time}")

            except (KeyError, ValueError, TypeError) as e:
                _LOGGER.debug("Error formatting schedule entry for attributes: %s", e)
                continue

        # Remove empty days from structured schedule
        rv[ATTR_SCHEDULE] = {day: times for day, times in structured_schedule.items() if times}

        if schedule_summary:
            rv[ATTR_SCHEDULE_ENTRIES] = schedule_summary
            rv[ATTR_SCHEDULE_COUNT] = len(schedule_summary)

        return rv

    @callback
    def _handle_coordinator_update(self) -> None:
        self.last_change = datetime.now(timezone.utc)
        if self.coordinator.data:
            conf = {
                CONF_NAME: self._attr_name,
                CONF_ICON: self._attr_icon,
                CONF_ID: self._attr_unique_id,
            }
            skipped_invalid = 0

            for sched in self.coordinator.data:
                # Filter out disabled entries
                if not sched.get(FIELD_ENABLED, True):
                    continue

                # Validate schedule entry
                if not validate_schedule_entry(sched):
                    skipped_invalid += 1
                    continue

                if sched[self.schedule["field"]]:
                    try:
                        start = time(sched[self.schedule["prefix"] + FIELD_START_TIME_SUFFIX][FIELD_HOUR],
                                     sched[self.schedule["prefix"] + FIELD_START_TIME_SUFFIX][FIELD_MINUTE])
                        end = time(sched[self.schedule["prefix"] + FIELD_END_TIME_SUFFIX][FIELD_HOUR],
                                   sched[self.schedule["prefix"] + FIELD_END_TIME_SUFFIX][FIELD_MINUTE])
                        if end.hour == 23 and end.minute == 59:
                            end = time.max

                        for day in range(len(sched[FIELD_DAYSOFWEEK])):
                            if sched[FIELD_DAYSOFWEEK][day]:
                                weekday = conf.setdefault(WEEKDAY_TO_CONF[week_0_sun_to_mon(day)], [])
                                weekday.append({CONF_FROM: start, CONF_TO: end, })
                    except (KeyError, ValueError, TypeError) as e:
                        _LOGGER.warning("Error processing schedule entry: %s", e)
                        skipped_invalid += 1

            if skipped_invalid > 0:
                _LOGGER.warning("Skipped %d invalid schedule entries", skipped_invalid)

            self._config = ENTITY_SCHEMA(conf)
            self._clean_up_listener()
            self._update()

    # UI-based update of this field.
    async def async_update_config(self, config: ConfigType) -> None:
        _LOGGER.debug("Starting schedule update for %s", self._attr_name)
        if self.coordinator.data:
            new_schedule = []
            index = 0

            try:
                # Process existing schedules
                for sched in self.coordinator.data:
                    if not validate_schedule_entry(sched):
                        continue

                    if sched[FIELD_INSIDE] and sched[FIELD_OUTSIDE]:
                        sched[self.schedule["field"]] = False
                        sched[FIELD_INDEX] = index
                        new_schedule.append(sched)
                        index = index + 1
                    if not sched[self.schedule["field"]] and (sched[FIELD_INSIDE] or sched[FIELD_OUTSIDE]):
                        sched[FIELD_INDEX] = index
                        new_schedule.append(sched)
                        index = index + 1

                # Process new schedule entries from config
                for day, dayName in WEEKDAY_TO_CONF.items():
                    if dayName in config:
                        for sched in config[dayName]:
                            try:
                                schedule = deepcopy(schedule_template)
                                schedule[FIELD_INDEX] = index
                                schedule[FIELD_DAYSOFWEEK][week_0_mon_to_sun(day)] = 1
                                schedule[self.schedule["field"]] = True
                                schedule[self.schedule["prefix"] + FIELD_START_TIME_SUFFIX][FIELD_HOUR] = sched[CONF_FROM].hour
                                schedule[self.schedule["prefix"] + FIELD_START_TIME_SUFFIX][FIELD_MINUTE] = sched[
                                    CONF_FROM].minute
                                schedule[self.schedule["prefix"] + FIELD_END_TIME_SUFFIX][FIELD_HOUR] = sched[CONF_TO].hour
                                schedule[self.schedule["prefix"] + FIELD_END_TIME_SUFFIX][FIELD_MINUTE] = sched[CONF_TO].minute

                                if validate_schedule_entry(schedule):
                                    new_schedule.append(schedule)
                                    index += 1
                            except Exception as e:
                                _LOGGER.error("Error processing schedule entry for %s: %s", dayName, e)

                compressed_schedule = compress_schedule(new_schedule)

                # Fetch current schedules from device for incremental sync
                schedule_list = await self.client.send_message(CONFIG, CMD_GET_SCHEDULE_LIST, notify=True)
                current_device_schedule = []
                for idx in schedule_list:
                    try:
                        entry = await self.client.send_message(CONFIG, CMD_GET_SCHEDULE, index=idx, notify=True)
                        if entry:
                            current_device_schedule.append(entry)
                    except Exception as e:
                        _LOGGER.warning("Failed to fetch schedule entry %s: %s", idx, e)

                # Compute diff between current device state and new schedule
                indices_to_delete, entries_to_add = compute_schedule_diff(
                    current_device_schedule, compressed_schedule
                )

                if not indices_to_delete and not entries_to_add:
                    _LOGGER.debug("No schedule changes needed for %s", self._attr_name)
                    # Coordinator already has correct data from device
                else:
                    _LOGGER.debug("Schedule diff for %s: deleting %d entries, adding %d entries",
                                  self._attr_name, len(indices_to_delete), len(entries_to_add))

                    # Delete only entries that are being removed
                    for idx in indices_to_delete:
                        self.client.send_message(CONFIG, CMD_DELETE_SCHEDULE, index=idx)

                    # Find available indices for new entries
                    # Use indices we just freed, plus next available
                    used_indices = set(schedule_list) - set(indices_to_delete)
                    available_indices = list(indices_to_delete)  # Reuse freed indices first

                    # Add more indices if needed
                    next_idx = max(schedule_list) + 1 if schedule_list else 0
                    while len(available_indices) < len(entries_to_add):
                        while next_idx in used_indices:
                            next_idx += 1
                        available_indices.append(next_idx)
                        next_idx += 1

                    # Create new schedules on device with assigned indices
                    for i, sched in enumerate(entries_to_add):
                        sched[FIELD_INDEX] = available_indices[i]
                        self.client.send_message(CONFIG, CMD_SET_SCHEDULE, index=sched[FIELD_INDEX], schedule=sched)

                    # Build final schedule state for coordinator
                    # Keep device entries that weren't deleted, add new entries
                    final_schedule = [e for e in current_device_schedule
                                      if e[FIELD_INDEX] not in indices_to_delete]
                    final_schedule.extend(entries_to_add)
                    self.coordinator.async_set_updated_data(final_schedule)

                _LOGGER.debug("Schedule update completed for %s", self._attr_name)

            except Exception as e:
                _LOGGER.error("Failed to update schedule configuration: %s", e)
                raise

    @callback
    def handle_power_update(self, state: bool) -> None:
        self.power = state
        if self.enabled:
            self.async_schedule_update_ha_state()


async def async_handle_update_schedule_service(call) -> None:
    """Handle the update_schedule service call."""
    _LOGGER.debug("Service update_schedule called")

    # Extract entity_id from target or data
    entity_ids = call.data.get(ATTR_ENTITY_ID)
    if not entity_ids:
        # Try to get from target (service call format)
        if hasattr(call, 'target') and call.target:
            entity_ids = call.target.get(ATTR_ENTITY_ID)

    if not entity_ids:
        raise ValueError("entity_id is required")

    # Handle both single entity_id and list
    if isinstance(entity_ids, str):
        entity_ids = [entity_ids]

    schedule_data = call.data.get(ATTR_SCHEDULE)
    if not schedule_data:
        raise ValueError("schedule is required")

    # Get schedule component to find entities
    schedule_component = call.hass.data.get(SCHEDULE_DOMAIN)
    if not schedule_component:
        raise ValueError("Schedule component not available")

    # Process each entity
    for entity_id in entity_ids:
        entity = None

        # Try to get entity from schedule component using entity_id
        # EntityComponent stores entities by unique_id, so we need to search
        for entity_obj in schedule_component.entities:
            if entity_obj.entity_id == entity_id:
                entity = entity_obj
                break

        if not entity or not isinstance(entity, PetDoorSchedule):
            _LOGGER.warning("Entity %s is not a Power Pet Door schedule entity, skipping", entity_id)
            continue

        try:
            await entity.async_update_config(schedule_data)
        except Exception as e:
            _LOGGER.error("Failed to update schedule for entity %s: %s", entity_id, e)
            raise


async def async_setup_services(hass: HomeAssistant) -> None:
    """Set up services for the Power Pet Door integration."""
    if hass.services.has_service(DOMAIN, SERVICE_UPDATE_SCHEDULE):
        return

    async def update_schedule_handler(call):
        await async_handle_update_schedule_service(call)

    # Define service schema - schedule format matches Home Assistant Schedule component
    # entity_id can come from target or data, so we use make_entity_service_schema
    service_schema = cv.make_entity_service_schema({
        vol.Required(ATTR_SCHEDULE): cv.schema_with_slug_keys(
            cv.ensure_list(
                {
                    vol.Required(CONF_FROM): cv.time,
                    vol.Required(CONF_TO): cv.time,
                }
            )
        ),
    })

    hass.services.async_register(
        DOMAIN,
        SERVICE_UPDATE_SCHEDULE,
        update_schedule_handler,
        schema=service_schema
    )
    _LOGGER.debug("Registered service %s.%s", DOMAIN, SERVICE_UPDATE_SCHEDULE)


async def async_setup_entry(hass: HomeAssistant,
                            entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    host = entry.data.get(CONF_HOST)
    port = entry.data.get(CONF_PORT)
    name = entry.data.get(CONF_NAME)
    obj = hass.data[DOMAIN][f"{host}:{port}"]

    async def update_schedule() -> list[dict]:
        _LOGGER.debug("Requesting update of schedule")
        schedule = []

        try:
            schedule_list = await obj["client"].send_message(CONFIG, CMD_GET_SCHEDULE_LIST, notify=True)
            _LOGGER.debug("Found %d schedule indices", len(schedule_list))

            for idx in schedule_list:
                try:
                    schedule_entry = await obj["client"].send_message(CONFIG, CMD_GET_SCHEDULE, index=idx, notify=True)
                    if schedule_entry:
                        schedule.append(schedule_entry)
                    else:
                        _LOGGER.warning("Received empty response for schedule index %d", idx)
                except Exception as e:
                    _LOGGER.warning("Failed to fetch schedule entry at index %d: %s", idx, e)
                    continue

            _LOGGER.debug("Fetched %d of %d schedule entries", len(schedule), len(schedule_list))
            return schedule
        except Exception as e:
            _LOGGER.error("Failed to fetch schedule list from device: %s", e)
            return schedule

    schedule_coordinator = DataUpdateCoordinator(
        hass=hass,
        logger=_LOGGER,
        name=f"{name} Schedule",
        update_method=update_schedule,
        update_interval=timedelta(entry.options.get(CONF_REFRESH)))

    obj["client"].add_handlers(f"{name} Schedule", on_connect=schedule_coordinator.async_request_refresh)

    async_add_entities([
        PetDoorSchedule(client=obj["client"],
                        name=f"{name} Inside Schedule",
                        schedule=SCHEDULES["inside"],
                        coordinator=schedule_coordinator,
                        device=obj["device"]),
        PetDoorSchedule(client=obj["client"],
                        name=f"{name} Outside Schedule",
                        schedule=SCHEDULES["outside"],
                        coordinator=schedule_coordinator,
                        device=obj["device"]),
    ])
