from __future__ import annotations

import asyncio
import async_timeout
import logging
import json
import time
import queue
from datetime import datetime, timezone

from collections.abc import Callable

from .const import (
    COMMAND,
    CONFIG,
    PING,
    PONG,
    DOOR_STATUS,
    CMD_OPEN,
    CMD_OPEN_AND_HOLD,
    CMD_CLOSE,
    CMD_GET_SETTINGS,
    CMD_GET_SENSORS,
    CMD_GET_POWER,
    CMD_GET_AUTO,
    CMD_GET_DOOR_STATUS,
    CMD_DISABLE_INSIDE,
    CMD_ENABLE_INSIDE,
    CMD_DISABLE_OUTSIDE,
    CMD_ENABLE_OUTSIDE,
    CMD_DISABLE_AUTO,
    CMD_ENABLE_AUTO,
    CMD_POWER_ON,
    CMD_POWER_OFF,
    CMD_GET_HW_INFO,
    CMD_GET_DOOR_BATTERY,
    FIELD_SUCCESS,
    FIELD_DOOR_STATUS,
    FIELD_SETTINGS,
    FIELD_POWER,
    FIELD_INSIDE,
    FIELD_OUTSIDE,
    FIELD_AUTO,
    FIELD_FWINFO,
    FIELD_BATTERY_PERCENT,
    FIELD_BATTERY_PRESENT,
    FIELD_AC_PRESENT,
)

_LOGGER = logging.getLogger(__name__)

MAX_FAILED_MSG = 2
MAX_FAILED_PINGS = 3

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

def make_bool(v: str | int | bool):
    if isinstance(v, str):
        if v.lower() in ("1", "true", "yes", "on"):
            return True
        if v.lower() in ("0", "false", "no", "off"):
            return False
        return None
    elif isinstance(v, int):
        return v != 0
    else:
        return v

class PowerPetDoorClient:
    msgId = 1
    replyMsgId = None

    door_status_listeners: dict[str, Callable[[str], None]] = {}
    settings_listeners: dict[str, Callable[[dict], None]] = {}
    sensor_listeners: dict[str, dict[str, Callable[[bool], None]]] = {
        FIELD_POWER: {},
        FIELD_INSIDE: {},
        FIELD_OUTSIDE: {},
        FIELD_AUTO: {},
    }
    hw_info_listeners: dict[str, Callable[[dict], None]] = {}
    battery_listeners: dict[str, Callable[[dict], None]] = {}

    on_connect: Callable[[], None] | None = None
    on_disconnect: Callable[[], None] | None = None
    on_ping: Callable[[int], None] | None = None

    _shutdown = False
    _ownLoop = False
    _eventLoop = None
    _transport = None
    _keepalive = None
    _check_receipt = None
    _last_ping = None
    _last_command = None
    _failed_msg = 0
    _failed_pings = 0
    _buffer = ''
    _outstanding = {}
    _queue = queue.SimpleQueue()

    def __init__(self, host: str, port: int, keepalive: float, timeout: float,
                 reconnect: float, loop: EventLoop | None = None) -> None:
        self.cfg_host = host
        self.cfg_port = port
        self.cfg_keepalive = keepalive
        self.cfg_timeout = timeout
        self.cfg_reconnect = reconnect

        if loop:
            _LOGGER.info("Latching onto an existing event loop.")
            self._ownLoop = False
            self._eventLoop = loop
        else:
            self._ownLoop = True
            self._eventLoop = asyncio.new_event_loop()

    # Theses functions wrap asyncio but ensure the loop is correct!
    def ensure_future(self, *args: Any, **kwargs: Any):
        return asyncio.ensure_future(*args, loop=self._eventLoop, **kwargs)

    def run_coroutine_threadsafe(self, *args: Any, **kwargs: Any):
        return asyncio.run_coroutine_threadsafe(*args, loop=self._eventLoop, **kwargs)

    async def sleep(self, *args: Any, **kwargs: Any):
        return await asyncio.sleep(*args, loop=self._eventLoop, **kwargs)

    async def wait_for(self, *args: Any, **kwargs: Any):
        return await asyncio.wait_for(*args, loop=self._eventLoop, **kwargs)

    def add_listener(self, name: str,
                     door_status_update: Callable[[str], None] | None = None,
                     settings_update: Callable[[dict], None] | None = None,
                     sensor_update: dict[str, Callable[[bool], None]] | None = None,
                     hw_info_update: Callable[[dict], None] | None = None,
                     battery_update: Callable[[dict], None] | None = None) -> None:
        if door_status_update:
            self.door_status_listeners[name] = door_status_update
        if settings_update:
            self.settings_listeners[name] = settings_update
        if sensor_update:
            if "*" in sensor_update:
                self.sensor_listeners[FIELD_POWER][name] = sensor_update["*"]
                self.sensor_listeners[FIELD_INSIDE][name] = sensor_update["*"]
                self.sensor_listeners[FIELD_OUTSIDE][name] = sensor_update["*"]
                self.sensor_listeners[FIELD_AUTO][name] = sensor_update["*"]
            else:
                if FIELD_POWER in sensor_update:
                    self.sensor_listeners[FIELD_POWER][name] = sensor_update[FIELD_POWER]
                if FIELD_INSIDE in sensor_update:
                    self.sensor_listeners[FIELD_INSIDE][name] = sensor_update[FIELD_INSIDE]
                if FIELD_OUTSIDE in sensor_update:
                    self.sensor_listeners[FIELD_OUTSIDE][name] = sensor_update[FIELD_OUTSIDE]
                if FIELD_AUTO in sensor_update:
                    self.sensor_listeners[FIELD_AUTO][name] = sensor_update[FIELD_AUTO]
        if hw_info_update:
            self.hw_info_listeners[name] = hw_info_update
        if battery_update:
            self.battery_listeners[name] = battery_update

    def del_listener(self, name: str) -> None:
        del self.door_status_listeners[name]
        del self.settings_listeners[name]
        del self.sensor_listeners[FIELD_POWER][name]
        del self.sensor_listeners[FIELD_INSIDE][name]
        del self.sensor_listeners[FIELD_OUTSIDE][name]
        del self.sensor_listeners[FIELD_AUTO][name]
        del self.hw_info_listeners[name]
        del self.battery_listeners[name]

    def start(self) -> None:
        """Public method for initiating connectivity with the power pet door."""
        self._shutdown = False
        self.ensure_future(self.connect())

        if self._ownLoop:
            _LOGGER.info("Starting up our own event loop.")
            self._eventLoop.run_forever()
            self._eventLoop.close()
            _LOGGER.info("Connection shut down.")

    def stop(self) -> None:
        """Public method for shutting down connectivity with the power pet door."""
        self._shutdown = True

        _LOGGER.info("Shutting down Power Pet Door client connection...")
        self._eventLoop.call_soon_threadsafe(self.disconnect)
        if self._ownLoop:
            self._eventLoop.call_soon_threadsafe(self._eventLoop.stop)

    async def connect(self) -> None:
        """Internal method for making the physical connection."""
        _LOGGER.info(str.format("Started to connect to Power Pet Door... at {0}:{1}", self.cfg_host, self.cfg_port))
        try:
            async with async_timeout.timeout(self.cfg_timeout):
                coro = self._eventLoop.create_connection(lambda: self, self.cfg_host, self.cfg_port)
                await coro
        except:
            self.handle_connect_failure()

    def connection_made(self, transport) -> None:
        """asyncio callback for a successful connection."""
        _LOGGER.info("Connection Successful!")
        self._transport = transport
        if self.cfg_keepalive:
            self._keepalive = self.ensure_future(self.keepalive())

        self.dequeue_data();

        # Caller code
        if self.on_connect:
            self.on_connect()

    def connection_lost(self, exc) -> None:
        """asyncio callback for connection lost."""
        if not self._shutdown:
            _LOGGER.error('The server closed the connection. Reconnecting...')
            self.ensure_future(self.reconnect(self.cfg_reconnect))

    async def reconnect(self, delay) -> None:
        """Internal method for reconnecting."""
        await self.sleep(delay)
        await self.connect()

    def disconnect(self) -> None:
        """Internal method for forcing connection closure if hung."""
        _LOGGER.debug('Closing connection with server...')
        if self._keepalive:
            self._keepalive.cancel()
            self._keepalive = None
        if self._check_receipt:
            self._check_receipt.cancel()
            self._check_receipt = None
        if self._transport:
            self._transport.close()
            self._transport = None
        for future in self._outstanding.values():
            future.cancel("Connection Terminated")
        self._outstanding = {}
        self._last_ping = None
        self._last_command = None
        self._failed_msg = 0
        self._failed_pings = 0
        self._buffer = ''
        self._queue = queue.SimpleQueue()

        # Caller code
        if self.on_disconnect:
            self.on_disconnect()

    def handle_connect_failure(self) -> None:
        """Handler for if we fail to connect to the power pet door."""
        if not self._shutdown:
            _LOGGER.error('Unable to connect to power pet door.')
            self.disconnect()

    async def keepalive(self) -> None:
        _keepalive = self._keepalive
        await self.sleep(self.cfg_keepalive)
        if _keepalive and not _keepalive.cancelled():
            if self._last_ping is not None:
                self._failed_pings += 1
                if self._failed_pings < MAX_FAILED_PINGS:
                    _LOGGER.warning('Last PING not responded to {} of {}...'.format(self._failed_pings,
                        MAX_FAILED_PINGS))
                else:
                    _LOGGER.error('Last PING not responded to {} times.'.format(self._failed_pings))
                    self.disconnect()
                    return

            self._last_ping = str(round(time.time()*1000))
            self.send_message(PING, self._last_ping)

    async def check_receipt(self, rawdata) -> None:
        _check_receipt = self._check_receipt
        await self.sleep(self.cfg_timeout)
        if _check_receipt and not _check_receipt.cancelled():
            self._failed_msg += 1
            if self._failed_msg < MAX_FAILED_MSG:
                _LOGGER.warn('Did not receive a response to a {} message in more than {} seconds, retrying.'.format(self._last_command, self.cfg_timeout))
            else:
                _LOGGER.error('Did not receive a response to a {} message in more than {} seconds {} times, dropped.'.format(self._last_command, self.cfg_timeout, self._failed_msg))
                self._failed_msg = 0
        else:
            self._failed_msg = 0

        self._check_receipt = None
        if self._failed_msg == 0:
            self.dequeue_data()
        else:
            self._send_data(rawdata)

    def enqueue_data(self, data) -> None:
        self._queue.put(data)
        if self._transport and not self._check_receipt:
            self.dequeue_data();

    def _send_data(self, rawdata) -> None:
        if not self._transport:
            _LOGGER.warning('Attempted to write to the stream without a connection active')
            return
        if self._keepalive:
            self._keepalive.cancel()
            self._keepalive = None
        try:
            _LOGGER.debug(str.format('TX > {0}', rawdata))
            self._transport.write(rawdata)
            if self._last_command:
                self._check_receipt = self.ensure_future(self.check_receipt(rawdata))
            if self.cfg_keepalive:
                self._keepalive = self.ensure_future(self.keepalive())
        except RuntimeError as err:
            _LOGGER.error(str.format('Failed to write to the stream. ({0}) ', err))
            self.disconnect()

    def dequeue_data(self) -> None:
        """Raw data send- just make sure it's encoded properly and logged."""
        if self._queue.empty():
            return
        if self._check_receipt:
            _LOGGER.warning('Attempted to send data while another message is still outstanding')
            return
        if not self._transport:
            _LOGGER.warning('Attempted to write to the stream without a connection active')
            return
        try:
            data = self._queue.get_nowait()
            if COMMAND in data:
                self._last_command = data[COMMAND]
            elif CONFIG in data:
                self._last_command = data[CONFIG]
            elif PING in data:
                self._last_command = PONG
            else:
                _LOGGER.warn("Sending unknown command type")
                self._last_command = None

            self._failed_msg = 0
            rawdata = json.dumps(data).encode("ascii")
            self._send_data(rawdata)
        except queue.Empty as err:
            _LOGGER.warning('Attempted to dequeue from an empty queue')
            return

    def data_received(self, rawdata) -> None:
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
                    self.ensure_future(self.process_message(json.loads(block)))

                except json.JSONDecodeError as err:
                    _LOGGER.error(str.format('Failed to decode JSON block ({0}) ', err))

                end = find_end(self._buffer)

    async def process_message(self, msg) -> None:
        future = None
        if "msgID" in msg:
            self.replyMsgId = msg["msgID"]
            if self.replyMsgId in self._outstanding and not self._outstanding[self.replyMsgId].cancelled():
                future = self._outstanding[self.replyMsgId]

        if msg["CMD"] == self._last_command:
            if self._check_receipt:
                self._check_receipt.cancel()
                self._check_receipt = None
            self.dequeue_data()

        if msg[FIELD_SUCCESS] == "true":
            if msg["CMD"] in (CMD_GET_DOOR_STATUS, DOOR_STATUS):
                for callback in self.door_status_listeners.values():
                    callback(msg[FIELD_DOOR_STATUS])
                if future:
                    future.set_result(msg[FIELD_DOOR_STATUS])

            elif msg["CMD"] == CMD_GET_SETTINGS:
                for callback in self.settings_listeners.values():
                    callback(msg[FIELD_SETTINGS])
                keys = self.settings_listeners.keys()
                if self.sensor_listeners[FIELD_POWER]:
                    val = make_bool(msg[FIELD_SETTINGS][FIELD_POWER])
                    for name, callback in self.sensor_listeners[FIELD_POWER].items():
                        if name not in keys:
                            callback(val)
                if self.sensor_listeners[FIELD_INSIDE]:
                    val = make_bool(msg[FIELD_SETTINGS][FIELD_INSIDE])
                    for name, callback in self.sensor_listeners[FIELD_INSIDE].items():
                        if name not in keys:
                            callback(val)
                if self.sensor_listeners[FIELD_OUTSIDE]:
                    val = make_bool(msg[FIELD_SETTINGS][FIELD_OUTSIDE])
                    for name, callback in self.sensor_listeners[FIELD_OUTSIDE].items():
                        if name not in keys:
                            callback(val)
                if self.sensor_listeners[FIELD_AUTO]:
                    val = make_bool(msg[FIELD_SETTINGS][FIELD_AUTO])
                    for name, callback in self.sensor_listeners[FIELD_AUTO].items():
                        if name not in keys:
                            callback(val)
                if future:
                    future.set_result(msg[FIELD_SETTINGS])

            elif msg["CMD"] in (CMD_GET_SENSORS, CMD_ENABLE_INSIDE, CMD_DISABLE_INSIDE, CMD_ENABLE_OUTSIDE, CMD_DISABLE_OUTSIDE):
                fr = {}
                if FIELD_INSIDE in msg:
                    val: bool = make_bool(msg[FIELD_INSIDE])
                    fr[FIELD_INSIDE] = val
                    if self.sensor_listeners[FIELD_INSIDE]:
                        for callback in self.sensor_listeners[FIELD_INSIDE].values():
                            callback(val)
                if FIELD_OUTSIDE in msg:
                    val: bool = make_bool(msg[FIELD_OUTSIDE])
                    fr[FIELD_OUTSIDE] = val
                    if self.sensor_listeners[FIELD_OUTSIDE]:
                        for callback in self.sensor_listeners[FIELD_OUTSIDE].values():
                            callback(val)
                if future:
                    future.set_result(fr)

            elif msg["CMD"] in (CMD_GET_POWER, CMD_POWER_ON, CMD_POWER_OFF):
                if FIELD_POWER in msg:
                    val: bool = make_bool(msg[FIELD_POWER])
                    if self.sensor_listeners[FIELD_POWER]:
                        for callback in self.sensor_listeners[FIELD_POWER].values():
                            callback(val)
                    if future:
                        future.set_result(val)

            elif msg["CMD"] in (CMD_GET_AUTO, CMD_ENABLE_AUTO, CMD_DISABLE_AUTO):
                if FIELD_AUTO in msg:
                    val: bool = make_bool(msg[FIELD_AUTO])
                    if self.sensor_listeners[FIELD_AUTO]:
                        for callback in self.sensor_listeners[FIELD_AUTO].values():
                           callback(val)
                    if future:
                        future.set_result(val)

            elif msg["CMD"] == CMD_GET_HW_INFO:
                if FIELD_FWINFO in msg:
                    for callback in self.hw_info_listeners.values():
                        callback(msg[FIELD_FWINFO])
                    if future:
                        future.set_result(msg[FIELD_FWINFO])

            elif msg["CMD"] == CMD_GET_DOOR_BATTERY:
                data = {
                    FIELD_BATTERY_PERCENT: msg[FIELD_BATTERY_PERCENT],
                    FIELD_BATTERY_PRESENT: make_bool(msg[FIELD_BATTERY_PRESENT]),
                    FIELD_AC_PRESENT: make_bool(msg[FIELD_AC_PRESENT]),
                }
                for callback in self.battery_listeners.values():
                    callback(data)
                if future:
                    future.set_result(data)

            elif msg["CMD"] == PONG:
                if msg[PONG] == self._last_ping:
                    if self.on_ping:
                        diff = round(time.time()*1000) - int(self._last_ping)
                        self.on_ping(diff)
                    self._failed_pings = 0
                    self._last_ping = None

            if future and not future.done():
                future.cancel()

        else:
            if future:
                future.set_exception("Command Failed")
            _LOGGER.warn("Error reported: {}".format(json.dumps(msg)))

    def send_message(self, type: str, arg: str, notify: bool = False) -> asyncio.Future | None:
        msgId = self.msgId
        rv = None
        if notify:
            rv = self._eventLoop.create_future()
            self._outstanding[msgId] = rv

            def cleanup(arg: asyncio.Future) -> None:
                del self._outstanding[msgId]
            rv.add_done_callback(cleanup)

        self.msgId += 1
        self.enqueue_data({ type: arg, "msgId": msgId, "dir": "p2d" })
        return rv

    @property
    def available(self) -> bool:
        return (self._transport and not self._transport.is_closing())

    @property
    def host(self) -> str:
        return self.cfg_host

    @property
    def port(self) -> int:
        return self.cfg_port
