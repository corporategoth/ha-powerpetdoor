from __future__ import annotations

import asyncio
import async_timeout
import logging
import json
import time
import copy

from asyncio import ensure_future

import voluptuous as vol

from homeassistant.const import (
    CONF_NAME,
    CONF_HOST,
    CONF_PORT,
    CONF_TIMEOUT,
)

from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers.reload import async_setup_reload_service
from homeassistant.components.switch import SwitchEntity
from homeassistant.components.binary_sensor import DEVICE_CLASS_DOOR
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send

_LOGGER = logging.getLogger(__name__)

DOMAIN = "powerpetdoor"

DEFAULT_NAME = "Power Pet Door"
DEFAULT_PORT = 3000
DEFAULT_PING_TIMEOUT = 30.0
DEFAULT_CONNECT_TIMEOUT = 5.0
DEFAULT_CONFIG_TIMEOUT = 2.0

COMMAND = "cmd"
CONFIG = "config"
PING = "PING"

PLATFORM_SCHEMA = cv.PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Required(CONF_HOST): cv.string,
    vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
    vol.Optional(CONF_TIMEOUT, default=DEFAULT_PING_TIMEOUT): vol.Coerce(float),
})

ATTR_SENSOR = "sensor"

SENSOR_INSIDE = "inside"
SENSOR_OUTSIDE = "outside"

SENSOR_SCHEMA = vol.Schema({
    vol.Required(ATTR_SENSOR): vol.All(cv.string, vol.In(SENSOR_INSIDE, SENSOR_OUTSIDE))
})

SIGNAL_INSIDE_ENABLE = "POWERPET_ENABLE_INSIDE_{}"
SIGNAL_INSIDE_DISABLE = "POWERPET_DISABLE_INSIDE_{}"
SIGNAL_INSIDE_TOGGLE = "POWERPET_TOGGLE_INSIDE_{}"
SIGNAL_OUTSIDE_ENABLE = "POWERPET_ENABLE_OUTSIDE_{}"
SIGNAL_OUTSIDE_DISABLE = "POWERPET_DISABLE_OUTSIDE_{}"
SIGNAL_OUTSIDE_TOGGLE = "POWERPET_TOGGLE_OUTSIDE_{}"
SIGNAL_POWER_ON = "POWERPET_POWER_ON_{}"
SIGNAL_POWER_OFF = "POWERPET_POWER_OFF{}"
SIGNAL_POWER_TOGGLE = "POWERPET_POWER_TOGGLE_{}"

def find_end(s) -> int | None:
    if not len(s):
        return None

    if s[0] != '{':
        raise IndexError("Block does not start with '{'")

    parens = 0
    for i, c in enumerate(s):
        if c == '{':
            parens += 1
        elif c == '}':
            parens -= 1
 
        if parens == 0:
            return i+1

    return None



class PetDoor(SwitchEntity):
    msgId = 1
    replyMsgId = None
    state = None
    settings = {}

    _shutdown = False
    _ownLoop = False
    _eventLoop = None
    _transport = None
    _keepalive = None
    _buffer = ''

    _attr_device_class = DEVICE_CLASS_DOOR
    _attr_should_poll = False

    def __init__(self, config: ConfigType) -> None:
        self.config = config
        self._attr_name = config.get(CONF_NAME)

    async def async_added_to_hass(self) -> None:
        async_dispatcher_connect(self.hass, SIGNAL_INSIDE_ENABLE.format(self.entity_id), self.config_enable_inside)
        async_dispatcher_connect(self.hass, SIGNAL_INSIDE_DISABLE.format(self.entity_id), self.config_disable_inside)
        async_dispatcher_connect(self.hass, SIGNAL_INSIDE_TOGGLE.format(self.entity_id), self.config_toggle_inside)
        async_dispatcher_connect(self.hass, SIGNAL_OUTSIDE_ENABLE.format(self.entity_id), self.config_enable_outside)
        async_dispatcher_connect(self.hass, SIGNAL_OUTSIDE_DISABLE.format(self.entity_id), self.config_disable_outside)
        async_dispatcher_connect(self.hass, SIGNAL_OUTSIDE_TOGGLE.format(self.entity_id), self.config_toggle_outside)
        async_dispatcher_connect(self.hass, SIGNAL_POWER_ON.format(self.entity_id), self.config_power_on)
        async_dispatcher_connect(self.hass, SIGNAL_POWER_OFF.format(self.entity_id), self.config_power_off)
        async_dispatcher_connect(self.hass, SIGNAL_POWER_TOGGLE.format(self.entity_id), self.config_power_toggle)

        _LOGGER.info("Latching onto an existing event loop.")
        self._ownLoop = False
        self._eventLoop = self.hass.loop

        self.start()

    async def async_will_remove_from_hass(self) -> None:
        self.stop()

    def start(self):
        """Public method for initiating connectivity with the power pet door."""
        self._shutdown = False
        ensure_future(self.connect(), loop=self._eventLoop)

        if self._ownLoop:
            _LOGGER.info("Starting up our own event loop.")
            self._eventLoop.run_forever()
            self._eventLoop.close()
            _LOGGER.info("Connection shut down.")

    def stop(self):
        """Public method for shutting down connectivity with the power pet door."""
        self._shutdown = True

        if self._ownLoop:
            _LOGGER.info("Shutting down Power Pet Door client connection...")
            self._eventLoop.call_soon_threadsafe(self._eventLoop.stop)
        else:
            _LOGGER.info("An event loop was given to us- we will shutdown when that event loop shuts down.")

    async def connect(self):
        """Internal method for making the physical connection."""
        _LOGGER.info(str.format("Started to connect to Power Pet Door... at {0}:{1}", self.config.get(CONF_HOST), self.config.get(CONF_PORT)))
        try:
            async with async_timeout.timeout(DEFAULT_CONNECT_TIMEOUT):
                coro = self._eventLoop.create_connection(lambda: self, self.config.get(CONF_HOST), self.config.get(CONF_PORT))
                await coro
        except:
            self.handle_connect_failure()

    def connection_made(self, transport):
        """asyncio callback for a successful connection."""
        _LOGGER.info("Connection Successful!")
        self._transport = transport
        self._keepalive = asyncio.ensure_future(self.keepalive(), loop=self._eventLoop)
        self.send_message(CONFIG, "GET_SETTINGS")

    def connection_lost(self, exc):
        """asyncio callback for connection lost."""
        if not self._shutdown:
            _LOGGER.error('The server closed the connection. Reconnecting...')
            ensure_future(self.reconnect(30), loop=self._eventLoop)

    async def reconnect(self, delay):
        """Internal method for reconnecting."""
        self.disconnect()
        await asyncio.sleep(delay)
        await self.connect()

    def disconnect(self):
        """Internal method for forcing connection closure if hung."""
        _LOGGER.debug('Closing connection with server...')
        if self._transport:
            self._transport.close()

    def handle_connect_failure(self):
        """Handler for if we fail to connect to the power pet door."""
        if not self._shutdown:
            _LOGGER.error('Unable to connect to power pet door. Reconnecting...')
            ensure_future(self.reconnect(30), loop=self._eventLoop)

    async def keepalive(self):
        await asyncio.sleep(self.config.get(CONF_TIMEOUT))
        self.send_message(PING, str(round(time.time()*1000)))
        self._keepalive = asyncio.ensure_future(self.keepalive(), loop=self._eventLoop)

    def send_data(self, data):
        """Raw data send- just make sure it's encoded properly and logged."""
        if not self._transport:
            _LOGGER.warning('Attempted to write to the stream without a connection active')
            return
        if self._keepalive:
            self._keepalive.cancel()
        rawdata = json.dumps(data).encode("ascii")
        _LOGGER.debug(str.format('TX > {0}', rawdata))
        try:
            self._transport.write(rawdata)
            self._keepalive = asyncio.ensure_future(self.keepalive(), loop=self._eventLoop)
        except RuntimeError as err:
            _LOGGER.error(str.format('Failed to write to the stream. Reconnecting. ({0}) ', err))
            if not self._shutdown:
                ensure_future(self.reconnect(30), loop=self._eventLoop)

    def data_received(self, rawdata):
        """asyncio callback for any data recieved from the power pet door."""
        if rawdata != '':
            try:
                data = rawdata.decode('ascii')
                _LOGGER.debug('----------------------------------------')
                _LOGGER.debug(str.format('RX < {0}', data))

                self._buffer += data
            except:
                _LOGGER.error('Received invalid message. Skipping.')
                return

            end = find_end(self._buffer)
            while end:
                block = self._buffer[:end]
                self._buffer = self._buffer[end:]

                try:
                    _LOGGER.debug(f"Parsing: {block}")
                    self.process_message(json.loads(block))

                except json.JSONDecodeError as err:
                    _LOGGER.error(str.format('Failed to decode JSON block ({0}) ', err))

                end = find_end(self._buffer)

    def process_message(self, msg):
        if "msgID" in msg:
            self.replyMsgId = msg["msgID"]

        if "door_status" in msg:
            self.status = msg["door_status"]
            _LOGGER.debug(f"DOOR STATUS - {self.status}")
            self.async_update_ha_state()

        elif "settings" in msg:
            self.settings = msg["settings"]
            _LOGGER.info("DOOR SETTINGS - {}".format(json.dumps(self.settings)))
            self.async_update_ha_state(True)

    def send_message(self, type, arg) -> int:
        msgId = self.msgId
        self.msgId += 1
        self.send_data({ type: arg, "msgId": msgId, "dir": "p2d" })
        return msgId

    async def async_update(self):
        self.send_message(CONFIG, "GET_DOOR_STATUS")

    @property
    def available(self) -> bool:
        return (self._transport and not self._transport.is_closing())

    @property
    def is_on(self) -> bool | None:
        return (self.status not in ("DOOR_IDLE", "DOOR_CLOSED"))

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
        self.send_message(COMMAND, "OPEN")

    async def cmd_open_and_hold(self):
        self.send_message(COMMAND, "OPEN_AND_HOLD")

    async def cmd_close(self):
        self.send_message(COMMAND, "CLOSE")

    async def config_disable_inside(self):
        self.send_message(CONFIG, "DISABLE_INSIDE")

    async def config_enable_inside(self):
        self.send_message(CONFIG, "ENABLE_INSIDE")

    async def config_toggle_inside(self):
        if self.settings:
            if self.settings["inside"] == "true":
                await self.config_disable_inside()
            elif self.settings["inside"] == "false":
                await self.config_enable_inside()

    async def config_disable_outside(self):
        self.send_message(CONFIG, "DISABLE_OUTSIDE")

    async def config_enable_outside(self):
        self.send_message(CONFIG, "ENABLE_OUTSIDE")

    async def config_toggle_outside(self):
        if self.settings:
            if self.settings["outside"] == "true":
                await self.config_disable_outside()
            elif self.settings["outside"] == "false":
                await self.config_enable_outside()

    async def config_power_on(self):
        self.send_message(CONFIG, "POWER_ON")

    async def config_power_off(self):
        self.send_message(CONFIG, "POWER_OFF")

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
    #if not discovery_info:
    #    return

    # await async_setup_reload_service(hass, DOMAIN, ["switch"])
    async_add_entities([ PetDoor(config) ])

    @callback
    async def async_sensor_enable(service: ServiceCall):
        sensor = service.data.get(ATTR_SENSOR)
        entity_id = service.data["entity_id"]
        if sensor == SENSOR_INSIDE:
            async_dispatcher_send(hass, SIGNAL_INSIDE_ENABLE.format(entity_id))
        elif sensor == SENSOR_OUTSIDE:
            async_dispatcher_send(hass, SIGNAL_OUTSIDE_ENABLE.format(entity_id))

    @callback
    async def async_sensor_disable(service: ServiceCall):
        sensor = service.data.get(ATTR_SENSOR)
        entity_id = service.data["entity_id"]
        if sensor == SENSOR_INSIDE:
            async_dispatcher_send(hass, SIGNAL_INSIDE_DISABLE.format(entity_id))
        elif sensor == SENSOR_OUTSIDE:
            async_dispatcher_send(hass, SIGNAL_OUTSIDE_DISABLE.format(entity_id))

    @callback
    async def async_sensor_toggle(service: ServiceCall):
        sensor = service.data.get(ATTR_SENSOR)
        entity_id = service.data["entity_id"]
        if sensor == SENSOR_INSIDE:
            async_dispatcher_send(hass, SIGNAL_INSIDE_TOGGLE.format(entity_id))
        elif sensor == SENSOR_OUTSIDE:
            async_dispatcher_send(hass, SIGNAL_OUTSIDE_TOGGLE.format(entity_id))

    @callback
    async def async_power_on(service: ServiceCall):
        entity_id = service.data["entity_id"]
        async_dispatcher_send(hass, SIGNAL_POWER_ON.format(entity_id))

    @callback
    async def async_power_off(service: ServiceCall):
        entity_id = service.data["entity_id"]
        async_dispatcher_send(hass, SIGNAL_POWER_OFF.format(entity_id))

    @callback
    async def async_power_toggle(service: ServiceCall):
        entity_id = service.data["entity_id"]
        async_dispatcher_send(hass, SIGNAL_POWER_TOGGLE.format(entity_id))

    hass.services.async_register(DOMAIN, "enable_sensor", async_sensor_enable, SENSOR_SCHEMA)
    hass.services.async_register(DOMAIN, "disable_sensor", async_sensor_disable, SENSOR_SCHEMA)
    hass.services.async_register(DOMAIN, "toggle_sensor", async_sensor_toggle, SENSOR_SCHEMA)
    hass.services.async_register(DOMAIN, "power_on", async_power_on)
    hass.services.async_register(DOMAIN, "power_off", async_power_off)
    hass.services.async_register(DOMAIN, "power_toggle", async_power_toggle)
