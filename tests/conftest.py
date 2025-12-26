"""Pytest configuration and fixtures for Power Pet Door tests."""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Callable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Try to import Home Assistant - these are optional for standalone tests
try:
    from homeassistant.core import HomeAssistant
    from homeassistant.const import CONF_HOST, CONF_PORT
    HAS_HOMEASSISTANT = True
except ImportError:
    HAS_HOMEASSISTANT = False
    CONF_HOST = "host"
    CONF_PORT = "port"

# Only load HA test plugin if available
try:
    import pytest_homeassistant_custom_component
    pytest_plugins = "pytest_homeassistant_custom_component"
except ImportError:
    pass

from custom_components.powerpetdoor.const import (
    DOMAIN,
    CONF_NAME,
    CONF_TIMEOUT,
    CONF_RECONNECT,
    CONF_KEEP_ALIVE,
    CONF_REFRESH,
    DEFAULT_PORT,
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_RECONNECT_TIMEOUT,
    DEFAULT_KEEP_ALIVE_TIMEOUT,
    DEFAULT_REFRESH_TIMEOUT,
    PING,
    PONG,
    FIELD_SUCCESS,
)
from custom_components.powerpetdoor.client import PowerPetDoorClient


# ============================================================================
# Mock Transport and Protocol
# ============================================================================

class MockTransport:
    """Mock asyncio transport for network simulation."""

    def __init__(self):
        self.written_data: list[bytes] = []
        self._closing = False
        self._closed = False

    def write(self, data: bytes) -> None:
        """Record written data."""
        self.written_data.append(data)

    def is_closing(self) -> bool:
        """Return whether transport is closing."""
        return self._closing

    def close(self) -> None:
        """Mark transport as closing."""
        self._closing = True

    def get_written_messages(self) -> list[dict]:
        """Parse and return all written JSON messages."""
        messages = []
        for data in self.written_data:
            try:
                messages.append(json.loads(data.decode('ascii')))
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
        return messages

    def get_last_message(self) -> dict | None:
        """Get the last written JSON message."""
        messages = self.get_written_messages()
        return messages[-1] if messages else None

    def clear(self) -> None:
        """Clear recorded data."""
        self.written_data.clear()


class MockDeviceProtocol:
    """Helper to simulate Power Pet Door device responses."""

    def __init__(self, client: PowerPetDoorClient):
        self.client = client
        self._auto_respond = True
        self._response_delay = 0.0

    async def send_response(self, response: dict) -> None:
        """Simulate device sending a response."""
        if self._response_delay > 0:
            await asyncio.sleep(self._response_delay)
        json_data = json.dumps(response).encode('ascii')
        self.client.data_received(json_data)

    def send_response_sync(self, response: dict) -> None:
        """Synchronously send a response (for non-async contexts)."""
        json_data = json.dumps(response).encode('ascii')
        self.client.data_received(json_data)

    def respond_to_ping(self, msg_id: int, ping_value: str) -> None:
        """Send PONG response to a PING."""
        self.send_response_sync({
            FIELD_SUCCESS: "true",
            "CMD": PONG,
            PONG: ping_value,
            "msgId": msg_id
        })

    def respond_success(self, msg_id: int, cmd: str, **extra) -> None:
        """Send a generic success response."""
        response = {
            FIELD_SUCCESS: "true",
            "CMD": cmd,
            "msgId": msg_id,
            **extra
        }
        self.send_response_sync(response)

    def respond_failure(self, msg_id: int, cmd: str, error: str = "error") -> None:
        """Send a generic failure response."""
        self.send_response_sync({
            FIELD_SUCCESS: "false",
            "CMD": cmd,
            "msgId": msg_id,
            "error": error
        })


# ============================================================================
# Mock Device Responses
# ============================================================================

MOCK_DOOR_STATUS = {
    "door_status": "DOOR_CLOSED",
}

MOCK_SETTINGS = {
    "inside": True,
    "outside": True,
    "auto": False,
    "power": True,
}

MOCK_SENSORS = {
    "inside_active": True,
    "outside_active": True,
    "auto_active": False,
}

MOCK_DOOR_BATTERY = {
    "batteryPercent": 85,
    "isDischarging": False,
    "isCharging": True,
}

MOCK_HARDWARE = {
    "hwVersion": "1.0",
    "fwVersion": "2.5.0",
}

MOCK_SCHEDULE_LIST = [0, 1, 2]

MOCK_SCHEDULE_ENTRY = {
    "index": 0,
    "daysOfWeek": [1, 1, 1, 1, 1, 0, 0],  # Mon-Fri
    "inside": True,
    "outside": False,
    "enabled": True,
    "in_start_time": {"hour": 6, "min": 0},
    "in_end_time": {"hour": 20, "min": 0},
    "out_start_time": {"hour": 0, "min": 0},
    "out_end_time": {"hour": 0, "min": 0},
}


def create_mock_response(cmd: str, msg_id: int, **extra) -> dict:
    """Factory function to create mock device responses."""
    responses = {
        "DOOR_STATUS": {**MOCK_DOOR_STATUS, "CMD": "DOOR_STATUS"},
        "GET_SETTINGS": {**MOCK_SETTINGS, "CMD": "GET_SETTINGS"},
        "GET_SENSORS": {**MOCK_SENSORS, "CMD": "GET_SENSORS"},
        "DOOR_BATTERY": {**MOCK_DOOR_BATTERY, "CMD": "DOOR_BATTERY"},
        "GET_HW_INFO": {**MOCK_HARDWARE, "CMD": "GET_HW_INFO"},
        "GET_SCHEDULE_LIST": {"schedules": MOCK_SCHEDULE_LIST, "CMD": "GET_SCHEDULE_LIST"},
        "GET_SCHEDULE": {**MOCK_SCHEDULE_ENTRY, "CMD": "GET_SCHEDULE"},
    }

    base_response = responses.get(cmd, {"CMD": cmd})
    return {
        FIELD_SUCCESS: "true",
        "msgId": msg_id,
        **base_response,
        **extra
    }


# ============================================================================
# Client Fixtures
# ============================================================================

@pytest.fixture
def mock_transport() -> MockTransport:
    """Create a mock transport."""
    return MockTransport()


@pytest.fixture
def event_loop():
    """Create an event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def client_config() -> dict:
    """Default client configuration."""
    return {
        "host": "192.168.1.100",
        "port": 3000,
        "timeout": 5.0,
        "reconnect": 1.0,  # Fast reconnect for tests
        "keepalive": 30.0,
    }


@pytest.fixture
def mock_client(event_loop, mock_transport, client_config) -> tuple[PowerPetDoorClient, MockTransport, MockDeviceProtocol]:
    """Create a PowerPetDoorClient with mocked transport.

    Returns:
        Tuple of (client, transport, device_protocol)
    """
    client = PowerPetDoorClient(
        host=client_config["host"],
        port=client_config["port"],
        timeout=client_config["timeout"],
        reconnect=client_config["reconnect"],
        keepalive=client_config["keepalive"],
        loop=event_loop
    )

    # Simulate connection established
    client._transport = mock_transport
    client.connection_made(mock_transport)

    # Create device protocol helper
    device = MockDeviceProtocol(client)

    return client, mock_transport, device


@pytest.fixture
def disconnected_client(event_loop, client_config) -> PowerPetDoorClient:
    """Create a PowerPetDoorClient without a connection."""
    client = PowerPetDoorClient(
        host=client_config["host"],
        port=client_config["port"],
        timeout=client_config["timeout"],
        reconnect=client_config["reconnect"],
        keepalive=client_config["keepalive"],
        loop=event_loop
    )
    return client


# ============================================================================
# Home Assistant Fixtures (only available if HA is installed)
# ============================================================================

if HAS_HOMEASSISTANT:
    @pytest.fixture
    def mock_config_entry(hass: HomeAssistant):
        """Create a mock config entry."""
        from homeassistant.config_entries import ConfigEntry
        from pytest_homeassistant_custom_component.common import MockConfigEntry

        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Power Pet Door",
            data={
                CONF_NAME: "Power Pet Door",
                CONF_HOST: "192.168.1.100",
                CONF_PORT: DEFAULT_PORT,
                CONF_TIMEOUT: DEFAULT_CONNECT_TIMEOUT,
                CONF_RECONNECT: DEFAULT_RECONNECT_TIMEOUT,
                CONF_KEEP_ALIVE: DEFAULT_KEEP_ALIVE_TIMEOUT,
                CONF_REFRESH: DEFAULT_REFRESH_TIMEOUT,
            },
            unique_id="192.168.1.100:3000",
        )
        entry.add_to_hass(hass)
        return entry


@pytest.fixture
def mock_setup_entry():
    """Mock the async_setup_entry function."""
    with patch(
        "custom_components.powerpetdoor.async_setup_entry",
        return_value=True
    ) as mock_setup:
        yield mock_setup


@pytest.fixture
def mock_connection():
    """Mock the network connection for config flow validation."""
    async def mock_open_connection(host, port):
        reader = AsyncMock()
        writer = MagicMock()

        # Mock the PING/PONG exchange
        ping_response = json.dumps({
            FIELD_SUCCESS: "true",
            "CMD": PONG,
            PONG: str(round(time.time() * 1000)),
        }).encode('ascii') + b'}'

        reader.readuntil = AsyncMock(return_value=ping_response)
        writer.write = MagicMock()
        writer.drain = AsyncMock()
        writer.close = MagicMock()
        writer.wait_closed = AsyncMock()

        return reader, writer

    with patch("asyncio.open_connection", side_effect=mock_open_connection):
        yield


@pytest.fixture
def mock_connection_timeout():
    """Mock a connection timeout."""
    with patch(
        "asyncio.open_connection",
        side_effect=asyncio.TimeoutError()
    ):
        yield


@pytest.fixture
def mock_connection_refused():
    """Mock a connection refused error."""
    with patch(
        "asyncio.open_connection",
        side_effect=ConnectionRefusedError()
    ):
        yield


# ============================================================================
# Utility Fixtures
# ============================================================================

@pytest.fixture
def callback_tracker() -> dict[str, list]:
    """Track callback invocations."""
    return {
        "calls": [],
        "args": [],
    }


@pytest.fixture
def make_callback(callback_tracker):
    """Factory to create tracked callbacks."""
    def factory(name: str = "callback"):
        def callback(*args, **kwargs):
            callback_tracker["calls"].append(name)
            callback_tracker["args"].append((args, kwargs))
        return callback
    return factory


@pytest.fixture
def make_async_callback(callback_tracker):
    """Factory to create tracked async callbacks."""
    def factory(name: str = "async_callback"):
        async def callback(*args, **kwargs):
            callback_tracker["calls"].append(name)
            callback_tracker["args"].append((args, kwargs))
        return callback
    return factory


# ============================================================================
# Snapshot Extension (for syrupy)
# ============================================================================

try:
    from pytest_homeassistant_custom_component.syrupy import HomeAssistantSnapshotExtension
    from syrupy.assertion import SnapshotAssertion

    @pytest.fixture
    def snapshot(snapshot: SnapshotAssertion) -> SnapshotAssertion:
        """Return snapshot assertion fixture with the Home Assistant extension."""
        return snapshot.use_extension(HomeAssistantSnapshotExtension)
except ImportError:
    # Syrupy not installed, skip snapshot fixture
    pass
