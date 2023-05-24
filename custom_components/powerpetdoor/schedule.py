from __future__ import annotations

from datetime import datetime, time, timezone, timedelta
from copy import deepcopy

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
    last_change = None
    power = True

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
            conf = {
                CONF_NAME: self._attr_name,
                CONF_ICON: self._attr_icon,
                CONF_ID: self._attr_unique_id,
            }
            for sched in self.coordinator.data:
                if sched[self.schedule["field"]]:
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
            self._config = ENTITY_SCHEMA(conf)
            self._clean_up_listener()
            self._update()

    # UI-based update of this field.
    async def async_update_config(self, config: ConfigType) -> None:
        if self.coordinator.data:
            new_schedule = []
            index = 0
            for sched in self.coordinator.data.items():
                if sched[FIELD_INSIDE] and sched[FIELD_OUTSIDE]:
                    sched[self.schedule["field"]] = False
                    sched[FIELD_INDEX] = index
                    new_schedule.append(sched)
                    index = index + 1
                if not sched[self.schedule["field"]] and (sched[FIELD_INSIDE] or sched[FIELD_OUTSIDE]):
                    sched[FIELD_INDEX] = index
                    new_schedule.append(sched)
                    index = index + 1

            for day, dayName in WEEKDAY_TO_CONF.items():
                if dayName in config:
                    for sched in config[dayName]:
                        schedule = deepcopy(schedule_template)
                        schedule[FIELD_INDEX] = index
                        schedule[FIELD_DAYSOFWEEK][week_0_mon_to_sun(day)] = 1
                        schedule[self.schedule["field"]] = True
                        schedule[self.schedule["prefix"] + FIELD_START_TIME_SUFFIX][FIELD_HOUR] = sched[CONF_FROM].hour
                        schedule[self.schedule["prefix"] + FIELD_START_TIME_SUFFIX][FIELD_MINUTE] = sched[
                            CONF_FROM].minute
                        schedule[self.schedule["prefix"] + FIELD_END_TIME_SUFFIX][FIELD_HOUR] = sched[CONF_TO].hour
                        schedule[self.schedule["prefix"] + FIELD_END_TIME_SUFFIX][FIELD_MINUTE] = sched[CONF_TO].minute
                        new_schedule.append(schedule)
                        index += 1

            self.coordinator.async_set_updated_data(compress_schedule(new_schedule))
            schedule_list = await self.client.send_message(CONFIG, CMD_GET_SCHEDULE_LIST)
            for idx in schedule_list:
                await self.client.send_message(CONFIG, CMD_DELETE_SCHEDULE, FIELD_INDEX=idx)
            for sched in new_schedule:
                await self.client.send_message(CONFIG, CMD_SET_SCHEDULE, FIELD_INDEX=sched[FIELD_INDEX], schedule=sched)

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
        _LOGGER.debug("Requesting update of schedule")
        schedule_list = await obj["client"].send_message(CONFIG, CMD_GET_SCHEDULE_LIST, notify=True)
        schedule = []
        for idx in schedule_list:
            schedule.append(await obj["client"].send_message(CONFIG, CMD_GET_SCHEDULE, index=idx, notify=True))
        return schedule

    schedule_coordinator = DataUpdateCoordinator(
        hass=hass,
        logger=_LOGGER,
        name=f"{name} Schedule",
        update_method=update_schedule,
        update_interval=timedelta(entry.options.get(CONF_REFRESH, entry.data.get(CONF_REFRESH))))

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
