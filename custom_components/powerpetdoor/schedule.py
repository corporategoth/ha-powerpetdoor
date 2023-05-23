from __future__ import annotations

from datetime import datetime, time, timezone, timedelta

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
        "prefix": "in",
        "icon": "mdi:home-clock",
        "category": EntityCategory.CONFIG,
    },
    "outside": {
        "field": FIELD_OUTSIDE,
        "prefix": "out",
        "icon": "mdi:sun-clock",
        "category": EntityCategory.CONFIG,
    },
}

def week_0_mon_to_sun(val: int) -> int:
    return (val + 8) % 7

def week_0_sun_to_mon(val: int) -> int:
    return (val + 6) % 7

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
                    start = time(sched[self.schedule["prefix"] + "_start_time"]["hour"],
                                 sched[self.schedule["prefix"] + "_start_time"]["min"])
                    stop = time(sched[self.schedule["prefix"] + "_end_time"]["hour"],
                                sched[self.schedule["prefix"] + "_end_time"]["min"])

                    for day in range(len(sched["daysOfWeek"])):
                        if sched["daysOfWeek"][day]:
                            weekday = conf.setdefault(WEEKDAY_TO_CONF[week_0_sun_to_mon(day)], [])
                            weekday.append({ CONF_FROM: start, CONF_TO: stop, })
            self._config = ENTITY_SCHEMA(conf)
            self._clean_up_listener()
            self._update()


    # UI-based update of this field.
    async def async_update_config(self, config: ConfigType) -> None:
        # TODO: Properly combine schedule entitiee

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
                    daysOfWeek = [0, 0, 0, 0, 0, 0, 0]
                    daysOfWeek[week_0_mon_to_sun(day)] = 1
                    for sched in config[dayName]:
                        schedule: {
                            FIELD_INDEX: index,
                            "daysOfWeek": daysOfWeek,
                            FIELD_INSIDE: False,
                            FIELD_OUTSIDE: False,
                            "enabled": True,
                            "in_start_time": {"hour": 0, "min": 0},
                            "in_end_time": {"hour": 0, "min": 0},
                            "out_start_time": {"hour": 0, "min": 0},
                            "out_end_time": {"hour": 0, "min": 0},
                        }
                        schedule[self.schedule["field"]] = True
                        schedule[self.schedule["prefix"] + "_start_time"]["hour"] = sched[CONF_FROM].hour
                        schedule[self.schedule["prefix"] + "_start_time"]["min"] = sched[CONF_FROM].minute
                        schedule[self.schedule["prefix"] + "_end_time"]["hour"] = sched[CONF_TO].hour
                        schedule[self.schedule["prefix"] + "_end_time"]["min"] = sched[CONF_TO].minute
                        new_schedule.append(schedule)
                        index += 1

            self.coordinator.async_set_updated_data(new_schedule)
            schedule_list = await self.client.send_message(CONFIG, CMD_GET_SCHEDULE_LIST)
            for idx in schedule_list:
                await self.client.send_message(CONFIG, CMD_DELETE_SCHEDULE, FIELD_INDEX=idx)
            for sched in new_schedule:
                await self.client.send_message(CONFIG, CMD_SET_SCHEDULE, FIELD_INDEX=sched[FIELD_INDEX], schedule=sched)

    @callback
    def handle_power_update(self, state: bool) -> None:
        self.power = state
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
