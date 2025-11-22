from __future__ import annotations

import json
import os
from datetime import datetime, time, timezone, timedelta
from copy import deepcopy
from pathlib import Path

from homeassistant.core import HomeAssistant, callback
from homeassistant.const import EntityCategory
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, CoordinatorEntity
from homeassistant.config_entries import ConfigEntry, SOURCE_IMPORT
from homeassistant.components.schedule import Schedule, WEEKDAY_TO_CONF, CONF_FROM, CONF_TO, ENTITY_SCHEMA
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
)

import logging

_LOGGER = logging.getLogger(__name__)

SCHEDULES = {
    "inside": {
        "field": FIELD_INSIDE,
        "prefix": FIELD_INSIDE_PREFIX,
        "icon": "mdi:home-clock",
        "category": EntityCategory.CONFIG,
        "disabled": False,
    },
    "outside": {
        "field": FIELD_OUTSIDE,
        "prefix": FIELD_OUTSIDE_PREFIX,
        "icon": "mdi:sun-clock",
        "category": EntityCategory.CONFIG,
        "disabled": False,
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
            _LOGGER.warning(f"Schedule entry missing index field: {sched}")
            return False
        
        if FIELD_DAYSOFWEEK not in sched:
            _LOGGER.warning(f"Schedule entry missing daysOfWeek field: {sched}")
            return False
        
        # Validate daysOfWeek is a list of 7 elements
        if not isinstance(sched[FIELD_DAYSOFWEEK], list) or len(sched[FIELD_DAYSOFWEEK]) != 7:
            _LOGGER.warning(f"Schedule entry has invalid daysOfWeek format: {sched[FIELD_DAYSOFWEEK]}")
            return False
        
        # Validate time fields if inside or outside is enabled
        if sched.get(FIELD_INSIDE, False):
            in_start_key = FIELD_INSIDE_PREFIX + FIELD_START_TIME_SUFFIX
            in_end_key = FIELD_INSIDE_PREFIX + FIELD_END_TIME_SUFFIX
            if in_start_key not in sched or in_end_key not in sched:
                _LOGGER.warning(f"Schedule entry missing inside time fields: {sched}")
                return False
            if FIELD_HOUR not in sched[in_start_key] or FIELD_MINUTE not in sched[in_start_key]:
                _LOGGER.warning(f"Schedule entry has invalid inside start time: {sched[in_start_key]}")
                return False
            if FIELD_HOUR not in sched[in_end_key] or FIELD_MINUTE not in sched[in_end_key]:
                _LOGGER.warning(f"Schedule entry has invalid inside end time: {sched[in_end_key]}")
                return False
        
        if sched.get(FIELD_OUTSIDE, False):
            out_start_key = FIELD_OUTSIDE_PREFIX + FIELD_START_TIME_SUFFIX
            out_end_key = FIELD_OUTSIDE_PREFIX + FIELD_END_TIME_SUFFIX
            if out_start_key not in sched or out_end_key not in sched:
                _LOGGER.warning(f"Schedule entry missing outside time fields: {sched}")
                return False
            if FIELD_HOUR not in sched[out_start_key] or FIELD_MINUTE not in sched[out_start_key]:
                _LOGGER.warning(f"Schedule entry has invalid outside start time: {sched[out_start_key]}")
                return False
            if FIELD_HOUR not in sched[out_end_key] or FIELD_MINUTE not in sched[out_end_key]:
                _LOGGER.warning(f"Schedule entry has invalid outside end time: {sched[out_end_key]}")
                return False
        
        return True
    except Exception as e:
        _LOGGER.error(f"Error validating schedule entry: {e}", exc_info=True)
        return False


def export_schedule_to_file(hass: HomeAssistant, device_id: str, schedule_data: list[dict]) -> None:
    """Export schedule data to a JSON file with timestamp."""
    try:
        config_dir = Path(hass.config.config_dir)
        export_dir = config_dir / "powerpetdoor" / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"schedule_export_{timestamp}.json"
        filepath = export_dir / filename
        
        export_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "device_id": device_id,
            "schedule_count": len(schedule_data),
            "enabled_count": sum(1 for s in schedule_data if s.get(FIELD_ENABLED, True)),
            "schedules": schedule_data
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)
        
        _LOGGER.info(f"Schedule exported to {filepath}")
    except Exception as e:
        _LOGGER.error(f"Failed to export schedule to file: {e}", exc_info=True)


def cleanup_old_exports(hass: HomeAssistant, keep_count: int = 5) -> None:
    """Remove old export files, keeping only the most recent ones."""
    try:
        config_dir = Path(hass.config.config_dir)
        export_dir = config_dir / "powerpetdoor" / "exports"
        
        if not export_dir.exists():
            return
        
        # Get all schedule export files
        export_files = list(export_dir.glob("schedule_export_*.json"))
        
        if len(export_files) <= keep_count:
            _LOGGER.debug(f"Found {len(export_files)} export files, keeping all (limit: {keep_count})")
            return
        
        # Sort by modification time (newest first)
        export_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        
        # Keep the most recent files
        files_to_keep = export_files[:keep_count]
        files_to_delete = export_files[keep_count:]
        
        _LOGGER.info(f"Found {len(export_files)} export files, keeping {len(files_to_keep)}, deleting {len(files_to_delete)}")
        
        deleted_count = 0
        for file_to_delete in files_to_delete:
            try:
                file_to_delete.unlink()
                deleted_count += 1
                _LOGGER.debug(f"Deleted old export file: {file_to_delete.name}")
            except Exception as e:
                _LOGGER.warning(f"Failed to delete export file {file_to_delete.name}: {e}")
        
        _LOGGER.info(f"Cleanup completed: {deleted_count} files deleted")
    except Exception as e:
        _LOGGER.error(f"Failed to cleanup old export files: {e}", exc_info=True)


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
        index + 1

    return out


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
        return rv

    @callback
    def _handle_coordinator_update(self) -> None:
        self.last_change = datetime.now(timezone.utc)
        if self.coordinator.data:
            _LOGGER.debug(f"Received schedule data update for {self._attr_name}: {len(self.coordinator.data)} entries")
            conf = {
                CONF_NAME: self._attr_name,
                CONF_ICON: self._attr_icon,
                CONF_ID: self._attr_unique_id,
            }
            processed_count = 0
            skipped_disabled = 0
            skipped_invalid = 0
            
            for sched in self.coordinator.data:
                # Filter out disabled entries
                if not sched.get(FIELD_ENABLED, True):
                    skipped_disabled += 1
                    _LOGGER.debug(f"Skipping disabled schedule entry (index: {sched.get(FIELD_INDEX, 'unknown')})")
                    continue
                
                # Validate schedule entry
                if not validate_schedule_entry(sched):
                    skipped_invalid += 1
                    _LOGGER.warning(f"Skipping invalid schedule entry (index: {sched.get(FIELD_INDEX, 'unknown')})")
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
                        processed_count += 1
                    except (KeyError, ValueError, TypeError) as e:
                        _LOGGER.warning(f"Error processing schedule entry (index: {sched.get(FIELD_INDEX, 'unknown')}): {e}")
                        skipped_invalid += 1
            
            if skipped_disabled > 0:
                _LOGGER.debug(f"Skipped {skipped_disabled} disabled schedule entries")
            if skipped_invalid > 0:
                _LOGGER.warning(f"Skipped {skipped_invalid} invalid schedule entries")
            
            _LOGGER.info(f"Processed {processed_count} schedule entries for {self._attr_name}")
            self._config = ENTITY_SCHEMA(conf)
            self._clean_up_listener()
            self._update()

    # UI-based update of this field.
    async def async_update_config(self, config: ConfigType) -> None:
        _LOGGER.info(f"Starting schedule update for {self._attr_name}")
        if self.coordinator.data:
            new_schedule = []
            index = 0
            
            try:
                # Process existing schedules
                for sched in self.coordinator.data:
                    if not validate_schedule_entry(sched):
                        _LOGGER.warning(f"Skipping invalid schedule entry during update: {sched}")
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
                                else:
                                    _LOGGER.warning(f"Skipping invalid new schedule entry for {dayName}")
                            except Exception as e:
                                _LOGGER.error(f"Error processing schedule entry for {dayName}: {e}", exc_info=True)

                _LOGGER.info(f"Prepared {len(new_schedule)} schedule entries to sync to device")
                self.coordinator.async_set_updated_data(compress_schedule(new_schedule))
                
                # Delete existing schedules from device
                try:
                    schedule_list = await self.client.send_message(CONFIG, CMD_GET_SCHEDULE_LIST, notify=True)
                    _LOGGER.info(f"Deleting {len(schedule_list)} existing schedule entries from device")
                    deleted_count = 0
                    for idx in schedule_list:
                        try:
                            await self.client.send_message(CONFIG, CMD_DELETE_SCHEDULE, FIELD_INDEX=idx)
                            deleted_count += 1
                            _LOGGER.debug(f"Deleted schedule entry at index {idx}")
                        except Exception as e:
                            _LOGGER.error(f"Failed to delete schedule entry at index {idx}: {e}", exc_info=True)
                    _LOGGER.info(f"Successfully deleted {deleted_count} of {len(schedule_list)} schedule entries")
                except Exception as e:
                    _LOGGER.error(f"Failed to delete existing schedules: {e}", exc_info=True)
                    raise

                # Create new schedules on device
                _LOGGER.info(f"Creating {len(new_schedule)} schedule entries on device")
                created_count = 0
                for sched in new_schedule:
                    try:
                        await self.client.send_message(CONFIG, CMD_SET_SCHEDULE, FIELD_INDEX=sched[FIELD_INDEX], schedule=sched)
                        created_count += 1
                        _LOGGER.debug(f"Created schedule entry at index {sched[FIELD_INDEX]}")
                    except Exception as e:
                        _LOGGER.error(f"Failed to create schedule entry at index {sched[FIELD_INDEX]}: {e}", exc_info=True)
                
                _LOGGER.info(f"Successfully created {created_count} of {len(new_schedule)} schedule entries")
                
                if created_count < len(new_schedule):
                    _LOGGER.warning(f"Partial schedule sync: {created_count}/{len(new_schedule)} entries created")
                else:
                    _LOGGER.info(f"Schedule update completed successfully for {self._attr_name}")
                    
            except Exception as e:
                _LOGGER.error(f"Failed to update schedule configuration: {e}", exc_info=True)
                raise

    @callback
    def handle_power_update(self, state: bool) -> None:
        self.power = state
        if self.enabled:
            self.async_schedule_update_ha_state()


async def async_setup_entry(hass: HomeAssistant,
                            entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    host = entry.data.get(CONF_HOST)
    port = entry.data.get(CONF_PORT)
    name = entry.data.get(CONF_NAME)
    obj = hass.data[DOMAIN][f"{host}:{port}"]

    async def update_schedule() -> list[dict]:
        _LOGGER.info("Starting schedule fetch from device")
        device_id = f"{host}:{port}"
        schedule = []
        
        try:
            schedule_list = await obj["client"].send_message(CONFIG, CMD_GET_SCHEDULE_LIST, notify=True)
            _LOGGER.info(f"Found {len(schedule_list)} schedule indices: {schedule_list}")
            
            if len(schedule_list) == 0:
                _LOGGER.info("No schedules found on device")
                return schedule
            
            for idx in schedule_list:
                try:
                    _LOGGER.debug(f"Fetching schedule entry at index {idx}")
                    schedule_entry = await obj["client"].send_message(CONFIG, CMD_GET_SCHEDULE, index=idx, notify=True)
                    if schedule_entry:
                        schedule.append(schedule_entry)
                        _LOGGER.debug(f"Successfully fetched schedule entry at index {idx}")
                    else:
                        _LOGGER.warning(f"Received empty response for schedule index {idx}")
                except Exception as e:
                    _LOGGER.warning(f"Failed to fetch schedule entry at index {idx}: {e}", exc_info=True)
                    continue
            
            _LOGGER.info(f"Successfully fetched {len(schedule)} of {len(schedule_list)} schedule entries")
            
            # Export schedule to file
            if schedule:
                try:
                    export_schedule_to_file(hass, device_id, schedule)
                    cleanup_old_exports(hass, keep_count=5)
                except Exception as e:
                    _LOGGER.error(f"Failed to export schedule: {e}", exc_info=True)
            
            return schedule
        except Exception as e:
            _LOGGER.error(f"Failed to fetch schedule list from device: {e}", exc_info=True)
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
