from __future__ import annotations

import asyncio
import async_timeout
import logging
import json
import time
from datetime import datetime, timezone
import copy

from asyncio import ensure_future

import voluptuous as vol

from homeassistant.const import (
    CONF_NAME,
    CONF_HOST,
    CONF_PORT,
    CONF_TIMEOUT,
    ATTR_ENTITY_ID,
    SERVICE_TOGGLE,
    SERVICE_TURN_ON,
    SERVICE_TURN_OFF,
    SERVICE_OPEN,
    SERVICE_CLOSE,
)

from homeassistant.backports.enum import StrEnum
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers.reload import async_setup_reload_service
from homeassistant.components.switch import SwitchEntity
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers import entity_platform

_LOGGER = logging.getLogger(__name__)

DOMAIN = "powerpetdoor"
SCAN_INTERVAL = timedelta(seconds=30)

DEFAULT_NAME = "Power Pet Door"
DEFAULT_PORT = 3000
DEFAULT_CONNECT_TIMEOUT = 5.0
DEFAULT_RECONNECT_TIMEOUT = 30.0
DEFAULT_KEEP_ALIVE_TIMEOUT = 30.0
DEFAULT_REFRESH_TIMEOUT = 300.0
DEFAULT_HOLD = True

COMMAND = "cmd"
CONFIG = "config"
PING = "PING"

CONF_REFRESH = "refresh"
CONF_KEEP_ALIVE = "keep_alive"
CONF_RECONNECT = "reconnect"
CONF_HOLD = "hold"

SERVICE_ENABLE_SENSOR = "enable_sensor"
SERVICE_DISABLE_SENSOR = "disable_sensor"
SERVICE_TOGGLE_SENSOR = "toggle_sensor"
SERVICE_ENABLE_AUTO = "enable_auto"
SERVICE_DISABLE_AUTO = "disable_auto"
SERVICE_TOGGLE_AUTO = "toggle_auto"
SERVICE_POWER_ON = "power_on"
SERVICE_POWER_OFF = "power_off"
SERVICE_POWER_TOGGLE = "toggle_power"

PLATFORM_SCHEMA = cv.PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Required(CONF_HOST): cv.string,
    vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
    vol.Optional(CONF_TIMEOUT, default=DEFAULT_CONNECT_TIMEOUT): cv.time_period_seconds,
    vol.Optional(CONF_RECONNECT, default=DEFAULT_RECONNECT_TIMEOUT): cv.time_period_seconds,
    vol.Optional(CONF_KEEP_ALIVE, default=DEFAULT_KEEP_ALIVE_TIMEOUT): cv.time_period_seconds,
    vol.Optional(CONF_REFRESH, default=DEFAULT_REFRESH_TIMEOUT): cv.time_period_seconds,
    vol.Optional(CONF_HOLD, default=DEFAULT_HOLD): cv.boolean,
})

ATTR_SENSOR = "sensor"

class SensorTypeClass(StrEnum):
    INSIDE = "inside"
    OUTSIDE = "outside"

SENSOR_SCHEMA = vol.Schema({
    vol.Required(ATTR_SENSOR): vol.All(cv.string, vol.In(SensorTypeClass.INSIDE, SensorTypeClass.OUTSIDE))
})

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
    status = None
    last_change = None
    settings = {}

    _shutdown = False
    _ownLoop = False
    _eventLoop = None
    _transport = None
    _keepalive = None
    _refresh = None
    _buffer = ''

    _attr_device_class = BinarySensorDeviceClass.DOOR
    _attr_should_poll = False

    def __init__(self, config: ConfigType) -> None:
        self.config = config
        self._attr_name = config.get(CONF_NAME)

    async def async_added_to_hass(self) -> None:
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

        if self.eventLoop is None:
            _LOGGER.info("Starting up our own event loop.")
            self._ownLoop = True
            self._ownLoop = asyncio.new_event_loop()

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
            async with async_timeout.timeout(self.config.get(CONF_TIMEOUT).total_seconds()):
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
            ensure_future(self.reconnect(self.config.get(CONF_RECONNECT).total_seconds()), loop=self._eventLoop)

    async def reconnect(self, delay):
        """Internal method for reconnecting."""
        self.disconnect()
        await asyncio.sleep(delay)
        await self.connect()

    def disconnect(self):
        """Internal method for forcing connection closure if hung."""
        _LOGGER.debug('Closing connection with server...')
        if self._keepalive:
            self._keepalive.cancel()
            self._keepalive = None
        if self._refresh:
            self._refresh.cancel()
            self._refresh = None
        if self._transport:
            self._transport.close()
            self._transport = None
        self_.buffer = ''

    def handle_connect_failure(self):
        """Handler for if we fail to connect to the power pet door."""
        if not self._shutdown:
            _LOGGER.error('Unable to connect to power pet door. Reconnecting...')
            ensure_future(self.reconnect(self.config.get(CONF_RECONNECT).total_seconds()), loop=self._eventLoop)

    async def keepalive(self):
        await asyncio.sleep(self.config.get(CONF_KEEP_ALIVE).total_seconds())
        if not self._keepalive.cancelled():
            self.send_message(PING, str(round(time.time()*1000)))
            self._keepalive = asyncio.ensure_future(self.keepalive(), loop=self._eventLoop)

    async def refresh(self):
        await asyncio.sleep(self.config.get(CONF_REFRESH).total_seconds())
        if not self._refresh.cancelled():
            self.send_message(CONFIG, "GET_SETTINGS")
            self._refresh = asyncio.ensure_future(self.refresh(), loop=self._eventLoop)

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
                ensure_future(self.reconnect(self.config.get(CONF_RECONNECT).total_seconds()), loop=self._eventLoop)

    def data_received(self, rawdata):
        """asyncio callback for any data recieved from the power pet door."""
        if rawdata != '':
            try:
                data = rawdata.decode('ascii')
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

        if msg["success"] == "true":
            if msg["CMD"] in ("GET_DOOR_STATUS", "DOOR_STATUS"):
                if self.status is not None and self.status != msg["door_status"]:
                    self.last_change = datetime.now(timezone.utc)
                self.status = msg["door_status"]
                self.schedule_update_ha_state()

            if msg["CMD"] == "GET_SETTINGS":
                if self._refresh:
                    self._refresh.cancel()

                self.settings = msg["settings"]
                _LOGGER.info("DOOR SETTINGS - {}".format(json.dumps(self.settings)))
                self.schedule_update_ha_state(self.status is None)
                self._refresh = asyncio.ensure_future(self.refresh(), loop=self._eventLoop)

            if msg["CMD"] in ("GET_SENSORS", "ENABLE_INSIDE", "DISABLE_INSIDE", "ENABLE_OUTSIDE", "DISABLE_OUTSIDE"):
                if "inside" in msg:
                    self.settings["inside"] = "true" if msg["inside"] else "false"
                if "outside" in msg:
                    self.settings["outside"] = "true" if msg["outside"] else "false"
                self.schedule_update_ha_state()

            if msg["CMD"] in ("GET_POWER", "POWER_ON", "POWER_OFF"):
                if "power_state" in msg:
                    self.settings["power_state"] = msg["power_state"]
                self.schedule_update_ha_state()

            if msg["CMD"] in ("GET_TIMERS_ENABLED", "ENABLE_TIMERS", "DISABLE_TIMERS"):
                if "timersEnabled" in msg:
                    self.settings["timersEnabled"] = msg["timersEnabled"]
                self.schedule_update_ha_state()
        else:
            _LOGGER.warn("Error reported: {}".format(json.dumps(msg)))

    def send_message(self, type, arg) -> int:
        msgId = self.msgId
        self.msgId += 1
        self.send_data({ type: arg, "msgId": msgId, "dir": "p2d" })
        return msgId

    async def async_update(self):
        _LOGGER.debug("Requesting update of door status")
        self.send_message(CONFIG, "GET_DOOR_STATUS")

    @property
    def available(self) -> bool:
        return (self._transport and not self._transport.is_closing())

    @property
    def is_on(self) -> bool | None:
        return (self.status not in ("DOOR_IDLE", "DOOR_CLOSED"))

    @property
    def icon(self) -> str | None:
        if self.is_on:
            return "mdi:dog-side"
        else:
            return "mdi:dog-side-off"

    @property
    def extra_state_attributes(self) -> dict | None:
        data = copy.deepcopy(self.settings)
        if self.status:
            data["status"] = self.status
        if self.last_change:
            data["last_change"] = self.last_change.isoformat()
        return data

    @callback
    async def turn_on(self, call: ServiceCall) -> None:
        return asyncio.run_coroutine_threadsafe(self.async_turn_on(hold, **kwargs)).result()

    @callback
    async def async_turn_on(self, call: ServiceCall) -> None:
        if "hold" in call.data:
            hold = call.data["hold"]
        else:
            hold = self.config.get(CONF_HOLD)
        if hold:
            self.send_message(COMMAND, "OPEN_AND_HOLD")
        else:
            self.send_message(COMMAND, "OPEN")

    @callback
    async def turn_off(self, call: ServiceCall) -> None:
        return asyncio.run_coroutine_threadsafe(self.async_turn_off(**kwargs)).result()

    @callback
    async def async_turn_off(self, call: ServiceCall) -> None:
        self.send_message(COMMAND, "CLOSE")

    @callback
    async def config_disable_sensor(self, call: ServiceCall):
        sensor = call.data["sensor"]
        if sensor == SensorTypeClass.INSIDE:
            self.send_message(CONFIG, "DISABLE_INSIDE")
        elif sensor == SensorTypeClass.OUTSIDE:
            self.send_message(CONFIG, "DISABLE_OUTSIDE")

    @callback
    async def config_enable_inside(self, call: ServiceCall):
        sensor = call.data["sensor"]
        if sensor == SensorTypeClass.INSIDE:
            self.send_message(CONFIG, "ENABLE_INSIDE")
        elif sensor == SensorTypeClass.OUTSIDE:
            self.send_message(CONFIG, "ENABLE_OUTSIDE")

    @callback
    async def config_toggle_sensor(self, call: ServiceCall):
        if self.settings:
            sensor = call.data["sensor"]
            if sensor == SensorTypeClass.INSIDE:
                if self.settings["inside"] == "true":
                    self.send_message(CONFIG, "DISABLE_INSIDE")
                elif self.settings["inside"] == "false":
                    self.send_message(CONFIG, "ENABLE_INSIDE")
            elif sensor == SensorTypeClass.OUTSIDE:
                if self.settings["outside"] == "true":
                    self.send_message(CONFIG, "DISABLE_OUTSIDE")
                elif self.settings["outside"] == "false":
                    self.send_message(CONFIG, "ENABLE_OUTSIDE")

    @callback
    async def config_disable_auto(self, call: ServiceCall):
        self.send_message(CONFIG, "DISABLE_TIMERS")

    @callback
    async def config_enable_auto(self, call: ServiceCall):
        self.send_message(CONFIG, "ENABLE_TIMERS")

    @callback
    async def config_toggle_auto(self, call: ServiceCall):
        if self.settings:
            if self.settings["timersEnabled"] == "true":
                await self.config_disable_auto()
            elif self.settings["timersEnabled"] == "false":
                await self.config_enable_auto()

    @callback
    async def config_power_on(self, call: ServiceCall):
        self.send_message(CONFIG, "POWER_ON")

    @callback
    async def config_power_off(self, call: ServiceCall):
        self.send_message(CONFIG, "POWER_OFF")

    @callback
    async def config_power_toggle(self, call: ServiceCall):
        if self.settings:
            if self.settings["power_state"] == "true":
                await self.config_power_off()
            elif self.settings["power_state"] == "false":
                await self.config_power_on()


async def async_setup(hass: HomeAssistant,
                      config: ConfigType) -> bool:
    component = hass.data[DOMAIN] = EntityComponent(
        _LOGGER, DOMAIN, hass, SCAN_INTERVAL
    )

    await component.async_setup(config)

    platform = entity_platform.async_get_current_platform()

    platform.async_register_entity_service(SERVICE_TURN_OFF, {}, "async_turn_off")
    platform.async_register_entity_service(SERVICE_TURN_ON, {}, "async_turn_on")
    platform.async_register_entity_service(SERVICE_TOGGLE, {}, "async_toggle")
    platform.async_register_entity_service(SERVICE_CLOSE, {}, "async_turn_off")
    platform.async_register_entity_service(SERVICE_OPEN, {}, "async_turn_on")
    platform.async_register_entity_service(SERVICE_ENABLE_SENSOR, SENSOR_SCHEMA, "config_enable_sensor")
    platform.async_register_entity_service(SERVICE_DISABLE_SENSOR, SENSOR_SCHEMA, "config_disable_sensor")
    platform.async_register_entity_service(SERVICE_TOGGLE_SENSOR, SENSOR_SCHEMA, "config_toggle_sensor")
    platform.async_register_entity_service(SERVICE_ENABLE_AUTO, {}, "config_enable_auto")
    platform.async_register_entity_service(SERVICE_DISABLE_AUTO, {}, "config_disable_auto")
    platform.async_register_entity_service(SERVICE_TOGGLE_AUTO, {}, "config_toggle_auto")
    platform.async_register_entity_service(SERVICE_POWER_ON, {}, "config_power_on")
    platform.async_register_entity_service(SERVICE_POWER_OFF, {}, "config_power_off")
    platform.async_register_entity_service(SERVICE_POWER_TOGGLE, {}, "config_power_toggle")
