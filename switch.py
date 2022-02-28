import asyncio
import logging
import json
import time
import copy

import voluptuous as vol

from homeassistant.const import (
    CONF_NAME,
    CONF_HOST,
    CONF_PORT,
    CONF_TIMEOUT,
)

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.entity import ToggleEntity
import homeassistant.helpers.config_validation as cv
import homeassistant.helpers.dispatcher

from typing import TypeDict

_LOGGER = logging.getLogger(__name__)

DOMAIN = "powerpetdoor"

DEFAULT_PORT = 3000
DEFAULT_TIMEOUT = 30.0

COMMAND = "cmd"
CONFIG = "config"
PING = "PING"

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Required(CONF_NAME): cv.string,
        vol.Required(CONF_HOST): cv.string,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
        vol.Optional(CONF_TIMEOUT, default=DEFAULT_TIMEOUT): vol.Coerce(float),
    })
})

ATTR_SENSOR = "sensor"

SENSOR_INSIDE = "inside"
SENSOR_OUTSIDE = "outside"

SENSOR_SCHEMA = vol.Schema{
    vol.Required(ATTR_SENSOR): vol.All(cv.string, vol.In(SENSOR_INSIDE, SENSOR_OUTSIDE))
})

SIGNAL_INSIDE_ENABLE = "POWERPET_ENABLE_INSIDE_{}"
SIGNAL_INSIDE_DISABLE = "POWERPET_ENABLE_INSIDE_{}"
SIGNAL_INSIDE_TOGGLE = "POWERPET_ENABLE_INSIDE_{}"
SIGNAL_OUTSIDE_ENABLE = "POWERPET_ENABLE_OUTSIDE_{}"
SIGNAL_OUTSIDE_DISABLE = "POWERPET_ENABLE_OUTSIDE_{}"
SIGNAL_OUTSIDE_TOGGLE = "POWERPET_ENABLE_OUTSIDE_{}"
SIGNAL_POWER_ON = "POWERPET_ENABLE_POWER_{}"
SIGNAL_POWER_OFF = "POWERPET_ENABLE_POWER_{}"
SIGNAL_POWER_TOGGLE = "POWERPET_ENABLE_POWER_{}"

class PetDoor(ToggleEntity):
    msgId = 1
    replyMsgId = None
    reader = None
    writer = None
    state = None
    settings = {}

    _attr_device_class = DEVICE_CLASS_DOOR
    _attr_should_poll = False

    def __init__(self, config: ConfigType) -> None:
        self.config = config

    async def async_added_to_hass(self) -> None;
        await self.start()

        async_dispatcher_connect(self.hass, SIGNAL_INSIDE_ENABLE.format(self.entity_id), self.config_enable_inside)
        async_dispatcher_connect(self.hass, SIGNAL_INSIDE_DISABLE.format(self.entity_id), self.config_disable_inside)
        async_dispatcher_connect(self.hass, SIGNAL_INSIDE_TOGGLE.format(self.entity_id), self.config_toggle_inside)
        async_dispatcher_connect(self.hass, SIGNAL_OUTSIDE_ENABLE.format(self.entity_id), self.config_enable_outside)
        async_dispatcher_connect(self.hass, SIGNAL_OUTSIDE_DISABLE.format(self.entity_id), self.config_disable_outside)
        async_dispatcher_connect(self.hass, SIGNAL_OUTSIDE_TOGGLE.format(self.entity_id), self.config_toggle_outside)
        async_dispatcher_connect(self.hass, SIGNAL_POWER_ENABLE.format(self.entity_id), self.config_powerr_on)
        async_dispatcher_connect(self.hass, SIGNAL_POWER_DISABLE.format(self.entity_id), self.config_power_off)
        async_dispatcher_connect(self.hass, SIGNAL_POWER_TOGGLE.format(self.entity_id), self.config_power_toggle)

    async def async_will_remove_from_hass(self) -> None:
        await self.stop()

    async def start(self);
        if not self.available():
            try:
                self.reader, self.writer = await asyncio.open_connection(self.config[CONF_HOST], self.config[CONF_PORT])
            except OSError as err:
                _LOGGER.error("Could not connect to %s on port %s: %s", self.config[CONF_HOST, self.config[CONF_PORT], err)
                return

        id = await self.handle_output(CONFIG, "GET_DOOR_STATUS")
        try:
            await asyncio.wait_for(self.wait_for_msg(id), 5.0)
        except asyncio.TimeoutError:
            _LOGGER.error("Could not determine initial pet door state within 5 seconds")
            await self.stop()
            return

        id = await self.handle_output(CONFIG, "GET_SETTINGS")
        try:
            await asyncio.wait_for(self.wait_for_msg(id), 5.0)
        except asyncio.TimeoutError:
            _LOGGER.error("Could not determine pet door settings state within 5 seconds")
            await self.stop()
            return

        self.hass.async_create_task(self.loop())

    async def loop(self) -> None:
        while self.available():
            try:
                await asyncio.wait_for(handle_input(), self.config[CONF_TIMEOUT])
            except asyncio.TimeoutError:
                await self.handle_output(PING, str(round(time.time()*1000)))

    async def stop(self) -> None:
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()
        self.reader = None
        self.writer = None
        self.state = None
        self.settings = {}

    async def handle_input(self) -> int | None:
        if not self.reader:
            return

        try:
            rawdata = (await self.reader.readuntil(b'}')).decode('utf-8')
            while rawdata.count('{') != rawdata.count('}'):
                rawdata += (await self.reader.readuntil(b'}')).decode('utf-8')
        except asyncio.IncompleteReadError:
            return await self.stop()

        _LOGGER.debug(f"Received: {rawdata}")
        rsp = json.loads(rawdata)

        replyMsgId = None
        if "msgID" in rsp:
            replyMsgId = rsp["msgID"]
            self.replyMsgId = replyMsgId

        if "door_status" in rsp:
            self.status = rsp["door_status"]
            _LOGGER.debug(f"DOOR STATUS - {self.status}")
            self.async_write_ha_state()
        elif "settings" in rsp:
            self.settings = rsp["settings"]
            _LOGGER.info("DOOR SETTINGS - {}".format(json.dumps(self.settings)))
            self.async_write_ha_state))

        return replyMsgId

    async def handle_output(self, type, arg) -> int:
        if not self.writer:
            return

        msgId = self.msgId
        self.msgId += 1
        self.writer.write(json.dumps({
            type: arg,
            "msgID": msgId,
            "dir": "p2d",
        }).encode("utf-8"))
        await self.writer.drain()
        return msgId

    async def wait_for_msg(self, id: int):
        msg = await self.handle_input()
        while msg != id:
            msg = await self.handle_input()

    async def async_update(self):
        await self.handle_output(CONFIG, "GET_DOOR_STATUS")

    @property
    def available(self) -> bool:
        return (self.reader and self.writer)

    @property
    def is_on(self) -> bool:
        return self.status not in ("DOOR_IDLE", "DOOR_CLOSED")

    @property
    def extra_state_attributes(self) -> dict | None:
        data = copy.deepcopy(self.settings)
        data["status"] = self.status
        return data


    async def turn_on(self, hold: bool = True, **kwargs: Any) -> None:
        return asyncio.run_coroutine_threadsafe(self.async_turn_on(hold, **kwargs)).result()

    async def async_turn_on(self, hold: bool = True, **kwargs: Any) -> None:
        if hold:
            await self.cmd_open_and_hold()
        else:
            await self.cmd_open()

    async def turn_off(self, **kwargs: Any) -> None:
        return asyncio.run_coroutine_threadsafe(self.async_turn_off(**kwargs)).result()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.cmd_close()

    async def cmd_open(self):
        await handle_output(COMMAND, "OPEN")

    async def cmd_open_and_hold(self):
        await handle_output(COMMAND, "OPEN_AND_HOLD")

    async def cmd_open(self):
        await handle_output(COMMAND, "CLOSE")

    async def config_disable_inside(self):
        await handle_output(CONFIG, "DISABLE_INSIDE")

    async def config_enable_inside(self):
        await handle_output(CONFIG, "ENABLE_INSIDE")

    async def config_toggle_inside(self):
        if self.settings:
            if self.settings["inside"] == "true":
                await self.config_disable_inside()
            elif self.settings["inside"] == "false":
                await self.config_enable_inside()

    async def config_disable_outside(self):
        await handle_output(CONFIG, "DISABLE_OUTSIDE")

    async def config_enable_outside(self):
        await handle_output(CONFIG, "ENABLE_OUTSIDE")

    async def config_toggle_outside(self):
        if self.settings:
            if self.settings["outside"] == "true":
                await self.config_disable_outside()
            elif self.settings["outside"] == "false":
                await self.config_enable_outside()

    async def config_power_on(self):
        await handle_output(CONFIG, "POWER_ON")

    async def config_power_off(self):
        await handle_output(CONFIG, "POWER_OFF")

    async def config_power_toggle(self):
        if self.settings:
            if self.settings["power_state"] == "true":
                await self.config_power_off()
            elif self.settings["power_state"] == "false":
                await self.config_power_on()


async def async_setup_platform(hass: HomeAssistant,
                               config: ConfigType,
                               async_add_entities: AddEntitiesCallback,
                               discovery_info: DiscoveryInfoType | None = None) -> None:

    await async_setup_reload_service(hass, DOMAIN, ["binary_sensor"])
    async_add_entities([ PetDoor(config) ])

    async def async_sensor_enable(service: ServiceCall):
        sensor = service.data.get(ATTR_SENSOR)
        entity_id = service.data["entity_id"]
        if sensor == SENSOR_INSIDE:
            async_dispatcher_send(hass, SIGNAL_INSIDE_ENABLE.format(entity_id))
        elif sensor == SENSOR_OUTSIDE:
            async_dispatcher_send(hass, SIGNAL_OUTSIDE_ENABLE.format(entity_id))

    async def async_sensor_disable(service: ServiceCall):
        sensor = service.data.get(ATTR_SENSOR)
        entity_id = service.data["entity_id"]
        if sensor == SENSOR_INSIDE:
            async_dispatcher_send(hass, SIGNAL_INSIDE_DISABLE.format(entity_id))
        elif sensor == SENSOR_OUTSIDE:
            async_dispatcher_send(hass, SIGNAL_OUTSIDE_DISABLE.format(entity_id))

    async def async_sensor_toggle(service: ServiceCall):
        sensor = service.data.get(ATTR_SENSOR)
        entity_id = service.data["entity_id"]
        if sensor == SENSOR_INSIDE:
            async_dispatcher_send(hass, SIGNAL_INSIDE_TOGGLE.format(entity_id))
        elif sensor == SENSOR_OUTSIDE:
            async_dispatcher_send(hass, SIGNAL_OUTSIDE_TOGGLE.format(entity_id))

    async def async_power_on(service: ServiceCall):
        entity_id = service.data["entity_id"]
        async_dispatcher_send(hass, SIGNAL_POWER_ON.format(entity_id))

    async def async_power_off(service: ServiceCall):
        entity_id = service.data["entity_id"]
        async_dispatcher_send(hass, SIGNAL_POWER_OFF.format(entity_id))

    async def async_power_toggle(service: ServiceCall):
        entity_id = service.data["entity_id"]
        async_dispatcher_send(hass, SIGNAL_POWER_TOGGLE.format(entity_id))

    hass.services.async_register(DOMAIN, "enable_sensor", async_sensor_enable, SENSOR_SCHEMA)
    hass.services.async_register(DOMAIN, "disable_sensor", async_sensor_disable, SENSOR_SCHEMA)
    hass.services.async_register(DOMAIN, "toggle_sensor", async_sensor_toggle, SENSOR_SCHEMA)
    hass.services.async_register(DOMAIN, "power_on", async_power_on)
    hass.services.async_register(DOMAIN, "power_off", async_power_off)
    hass.services.async_register(DOMAIN, "power_toggle", async_power_toggle)
