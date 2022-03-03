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
    STATE_OPEN,
    STATE_OPENING,
    STATE_CLOSED,
    STATE_CLOSING
)

from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.reload import async_setup_reload_service
from homeassistant.helpers.entity import Entity
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers import entity_platform
import .const

_LOGGER = logging.getLogger(__name__)

PLATFORM_SCHEMA = cv.PLATFORM_SCHEMA.extend(CONFIG_SCHEMA).extend(CONFIG_SCHEMA_ADV)

DOOR_SCHEMA = {
    vol.Optional(ATTR_HOLD): cv.boolean
}

SENSOR_SCHEMA = {
    vol.Required(ATTR_SENSOR): vol.All(cv.string, vol.In([ SensorTypeClass.INSIDE, SensorTypeClass.OUTSIDE ]))
}

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

class PetDoor(Entity):
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
    _check_receipt = None
    _last_ping = None
    _buffer = ''

    _attr_device_class = BinarySensorDeviceClass.DOOR
    _attr_should_poll = False

    def __init__(self, config: ConfigType) -> None:
        self.config = config
        self._attr_name = self.config.get(CONF_NAME)

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

        if self._eventLoop is None:
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

        _LOGGER.info("Shutting down Power Pet Door client connection...")
        if self._ownLoop:
            self._eventLoop.call_soon_threadsafe(self._eventLoop.stop)
        else:
            asyncio.ensure_future(self.disconnect(), loop=self._eventLoop)

    async def connect(self):
        """Internal method for making the physical connection."""
        _LOGGER.info(str.format("Started to connect to Power Pet Door... at {0}:{1}", self.config.get(CONF_HOST), self.config.get(CONF_PORT)))
        try:
            async with async_timeout.timeout(self.config.get(CONF_TIMEOUT)):
                coro = self._eventLoop.create_connection(lambda: self, self.config.get(CONF_HOST), self.config.get(CONF_PORT))
                await coro
        except:
            self.handle_connect_failure()

    def connection_made(self, transport):
        """asyncio callback for a successful connection."""
        _LOGGER.info("Connection Successful!")
        self._transport = transport
        self._keepalive = asyncio.ensure_future(self.keepalive(), loop=self._eventLoop)
        self.send_message(CONFIG, CMD_GET_SETTINGS)

    def connection_lost(self, exc):
        """asyncio callback for connection lost."""
        if not self._shutdown:
            _LOGGER.error('The server closed the connection. Reconnecting...')
            ensure_future(self.reconnect(self.config.get(CONF_RECONNECT)), loop=self._eventLoop)

    async def reconnect(self, delay):
        """Internal method for reconnecting."""
        await self.disconnect()
        await asyncio.sleep(delay)
        await self.connect()

    async def disconnect(self):
        """Internal method for forcing connection closure if hung."""
        _LOGGER.debug('Closing connection with server...')
        if self._keepalive:
            self._keepalive.cancel()
            self._keepalive = None
        if self._refresh:
            self._refresh.cancel()
            self._refresh = None
        if self._check_receipt:
            self._check_receipt.close()
            self._check_receipt = None
        if self._transport:
            self._transport.close()
            self._transport = None
        self._last_ping = None
        self._buffer = ''

    def handle_connect_failure(self):
        """Handler for if we fail to connect to the power pet door."""
        if not self._shutdown:
            _LOGGER.error('Unable to connect to power pet door. Reconnecting...')
            ensure_future(self.reconnect(self.config.get(CONF_RECONNECT)), loop=self._eventLoop)

    async def keepalive(self):
        await asyncio.sleep(self.config.get(CONF_KEEP_ALIVE))
        if not self._keepalive.cancelled():
            if self._last_ping is not None:
                _LOGGER.error('Last PING not responded to. Reconnecting...')
                ensure_future(self.reconnect(self.config.get(CONF_RECONNECT)), loop=self._eventLoop)
                return

            self._last_ping = str(round(time.time()*1000))
            self.send_message(PING, self._last_ping)
            self._keepalive = asyncio.ensure_future(self.keepalive(), loop=self._eventLoop)

    async def check_receipt(self):
        await asyncio.sleep(self.config.get(CONF_TIMEOUT))
        if not self._check_receipt.cancelled():
            _LOGGER.error('Did not receive a response to a message in more than {} seconds.  Reconnecting...')
            ensure_future(self.reconnect(self.config.get(CONF_RECONNECT)), loop=self._eventLoop)
        self._check_receipt = None

    async def refresh(self):
        await asyncio.sleep(self.config.get(CONF_REFRESH))
        if not self._refresh.cancelled():
            self.send_message(CONFIG, CMD_GET_SETTINGS)
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
            if not self._check_receipt:
                self._check_receipt = asyncio.ensure_future(self.check_receipt(), loop=self._eventLoop)
            self._keepalive = asyncio.ensure_future(self.keepalive(), loop=self._eventLoop)
        except RuntimeError as err:
            _LOGGER.error(str.format('Failed to write to the stream. Reconnecting. ({0}) ', err))
            if not self._shutdown:
                ensure_future(self.reconnect(self.config.get(CONF_RECONNECT)), loop=self._eventLoop)

    def data_received(self, rawdata):
        """asyncio callback for any data recieved from the power pet door."""
        if rawdata != '':
            if self._check_receipt:
                self._check_receipt.cancel()
                self._check_receipt = None

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

        if msg[FIELD_SUCCESS] == "true":
            if msg["CMD"] in (CMD_GET_DOOR_STATUS, DOOR_STATUS):
                if self.status is not None and self.status != msg[FIELD_DOOR_STATUS]:
                    self.last_change = datetime.now(timezone.utc)
                self.status = msg[FIELD_DOOR_STATUS]
                self.schedule_update_ha_state()

            if msg["CMD"] == CMD_GET_SETTINGS:
                if self._refresh:
                    self._refresh.cancel()

                self.settings = msg[FIELD_SETTINGS]
                _LOGGER.info("DOOR SETTINGS - {}".format(json.dumps(self.settings)))
                self.schedule_update_ha_state(self.status is None)
                self._refresh = asyncio.ensure_future(self.refresh(), loop=self._eventLoop)

            if msg["CMD"] in (CMD_GET_SENSORS, CMD_ENABLE_INSIDE, CMD_DISABLE_INSIDE, CMD_ENABLE_OUTSIDE, CMD_DISABLE_OUTSIDE):
                if FIELD_INSIDE in msg:
                    self.settings[FIELD_INSIDE] = "true" if msg[FIELD_INSIDE] else "false"
                if FIELD_OUTSIDE in msg:
                    self.settings[FIELD_OUTSIDE] = "true" if msg[FIELD_OUTSIDE] else "false"
                self.schedule_update_ha_state()

            if msg["CMD"] in (CMD_GET_POWER, CMD_POWER_ON, CMD_POWER_OFF):
                if FIELD_POWER in msg:
                    self.settings[FIELD_POWER] = msg[FIELD_POWER]
                self.schedule_update_ha_state()

            if msg["CMD"] in (CMD_GET_AUTO, CMD_ENABLE_AUTO, CMD_DISABLE_AUTO):
                if FIELD_AUTO in msg:
                    self.settings[FIELD_AUTO] = msg[FIELD_AUTO]
                self.schedule_update_ha_state()

            if msg["CMD"] == PONG:
                if msg[PONG] == self._last_ping:
                    self._last_ping = None

        else:
            _LOGGER.warn("Error reported: {}".format(json.dumps(msg)))

    def send_message(self, type, arg) -> int:
        msgId = self.msgId
        self.msgId += 1
        self.send_data({ type: arg, "msgId": msgId, "dir": "p2d" })
        return msgId

    async def async_update(self):
        _LOGGER.debug("Requesting update of door status")
        self.send_message(CONFIG, CMD_GET_DOOR_STATUS)

    @property
    def available(self) -> bool:
        return (self._transport and not self._transport.is_closing())

    @property
    def state(self) -> Literal[STATE_CLOSED, STATE_OPEN, STATE_OPENING, STATE_CLOSING] | None:
        """Return the state."""
        if self.status is None:
            return None
        elif self.status in (DOOR_STATE_IDLE, DOOR_STATE_CLOSED):
            return STATE_CLOSED
        elif self.status == DOOR_STATE_HOLDING:
            return STATE_OPEN
        elif self.status in (DOOR_STATE_RISING, DOOR_STATE_SLOWING):
            return STATE_OPENING
        else:
            return STATE_CLOSING

    @property
    def is_on(self) -> bool | None:
        """Return True if entity is on."""
        return (self.status not in (DOOR_STATE_IDLE, DOOR_STATE_CLOSED))

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
        data["host"] = self.config.get(CONF_HOST)
        data["port"] = self.config.get(CONF_PORT)
        data["hold"] = self.config.get(CONF_HOLD)
        return data

    @callback
    async def turn_on(self, hold: bool | None = None, **kwargs: Any) -> None:
        """Turn the entity on."""
        return asyncio.run_coroutine_threadsafe(self.async_turn_on(hold, **kwargs)).result()

    @callback
    async def async_turn_on(self, hold: bool | None = None, **kwargs: Any) -> None:
        """Turn the entity on."""
        if hold is None:
            hold = self.config.get(CONF_HOLD)
        if hold:
            self.send_message(COMMAND, CMD_OPEN_AND_HOLD)
        else:
            self.send_message(COMMAND, CMD_OPEN)

    @callback
    async def turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        return asyncio.run_coroutine_threadsafe(self.async_turn_off(**kwargs)).result()

    @callback
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        self.send_message(COMMAND, CMD_CLOSE)

    def toggle(self, **kwargs: Any) -> None:
        """Toggle the entity."""
        if self.is_on:
            self.turn_off(**kwargs)
        else:
            self.turn_on(**kwargs)

    async def async_toggle(self, **kwargs: Any) -> None:
        """Toggle the entity."""
        if self.is_on:
            await self.async_turn_off(**kwargs)
        else:
            await self.async_turn_on(**kwargs)

    @callback
    async def config_disable_sensor(self, sensor: SensorTypeClass | str, **kwargs: Any):
        if sensor == SensorTypeClass.INSIDE:
            self.send_message(CONFIG, CMD_DISABLE_INSIDE)
        elif sensor == SensorTypeClass.OUTSIDE:
            self.send_message(CONFIG, CMD_DISABLE_OUTSIDE)

    @callback
    async def config_enable_sensor(self, sensor: SensorTypeClass | str, **kwargs: Any):
        if sensor == SensorTypeClass.INSIDE:
            self.send_message(CONFIG, CMD_ENABLE_INSIDE)
        elif sensor == SensorTypeClass.OUTSIDE:
            self.send_message(CONFIG, CMD_ENABLE_OUTSIDE)

    @callback
    async def config_toggle_sensor(self, sensor: SensorTypeClass | str, **kwargs: Any):
        if self.settings:
            if sensor == SensorTypeClass.INSIDE:
                if self.settings[FIELD_INSIDE] == "true":
                    self.send_message(CONFIG, CMD_DISABLE_INSIDE)
                elif self.settings[FIELD_INSIDE] == "false":
                    self.send_message(CONFIG, CMD_ENABLE_INSIDE)
            elif sensor == SensorTypeClass.OUTSIDE:
                if self.settings[FIELD_OUTSIDE] == "true":
                    self.send_message(CONFIG, CMD_DISABLE_OUTSIDE)
                elif self.settings[FIELD_OUTSIDE] == "false":
                    self.send_message(CONFIG, CMD_ENABLE_OUTSIDE)

    @callback
    async def config_disable_auto(self, **kwargs: Any):
        self.send_message(CONFIG, CMD_DISABLE_AUTO)

    @callback
    async def config_enable_auto(self, **kwargs: Any):
        self.send_message(CONFIG, CMD_ENABLE_AUTO)

    @callback
    async def config_toggle_auto(self, **kwargs: Any):
        if self.settings:
            if self.settings[FIELD_AUTO] == "true":
                await self.config_disable_auto()
            elif self.settings[FIELD_AUTO] == "false":
                await self.config_enable_auto()

    @callback
    async def config_power_on(self, **kwargs: Any):
        self.send_message(CONFIG, CMD_POWER_ON)

    @callback
    async def config_power_off(self, **kwargs: Any):
        self.send_message(CONFIG, CMD_POWER_OFF)

    @callback
    async def config_power_toggle(self, **kwargs: Any):
        if self.settings:
            if self.settings[FIELD_POWER] == "true":
                await self.config_power_off()
            elif self.settings[FIELD_POWER] == "false":
                await self.config_power_on()


async def async_setup_platform(hass: HomeAssistant,
                               config: ConfigType,
                               async_add_entities: AddEntitiesCallabck,
                               discovery_info: DiscoveryInfoType | None = None) -> None:

    async_add_entities([ PetDoor(config) ])

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(SERVICE_CLOSE, {}, "async_turn_off")
    platform.async_register_entity_service(SERVICE_OPEN, DOOR_SCHEMA, "async_turn_on")
    platform.async_register_entity_service(SERVICE_TOGGLE, DOOR_SCHEMA, "async_toggle")
    platform.async_register_entity_service(SERVICE_ENABLE_SENSOR, SENSOR_SCHEMA, "config_enable_sensor")
    platform.async_register_entity_service(SERVICE_DISABLE_SENSOR, SENSOR_SCHEMA, "config_disable_sensor")
    platform.async_register_entity_service(SERVICE_TOGGLE_SENSOR, SENSOR_SCHEMA, "config_toggle_sensor")
    platform.async_register_entity_service(SERVICE_ENABLE_AUTO, {}, "config_enable_auto")
    platform.async_register_entity_service(SERVICE_DISABLE_AUTO, {}, "config_disable_auto")
    platform.async_register_entity_service(SERVICE_TOGGLE_AUTO, {}, "config_toggle_auto")
    platform.async_register_entity_service(SERVICE_POWER_ON, {}, "config_power_on")
    platform.async_register_entity_service(SERVICE_POWER_OFF, {}, "config_power_off")
    platform.async_register_entity_service(SERVICE_POWER_TOGGLE, {}, "config_power_toggle")

# Right now this can be an alias for the above
async def async_setup_entry(hass: HomeAssistant,
                            entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:

    await async_setup_platform(hass, entry.data, async_add_entities)
