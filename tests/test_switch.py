# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""Tests for Power Pet Door switch entities."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Skip all tests in this module if Home Assistant is not available
pytest.importorskip("homeassistant")
pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.core import HomeAssistant
from homeassistant.components.switch import SwitchDeviceClass
from homeassistant.const import EntityCategory
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from custom_components.powerpetdoor.switch import (
    PetDoorSwitch,
    PetDoorNotificationSwitch,
    ConnectionSwitch,
    SWITCHES,
    NOTIFICATION_SWITCHES,
)
from custom_components.powerpetdoor.client import make_bool
from custom_components.powerpetdoor.const import (
    CONFIG,
    CMD_ENABLE_INSIDE,
    CMD_DISABLE_INSIDE,
    CMD_ENABLE_OUTSIDE,
    CMD_DISABLE_OUTSIDE,
    CMD_POWER_ON,
    CMD_POWER_OFF,
    CMD_ENABLE_AUTO,
    CMD_DISABLE_AUTO,
    CMD_ENABLE_CMD_LOCKOUT,
    CMD_DISABLE_CMD_LOCKOUT,
    CMD_SET_NOTIFICATIONS,
    FIELD_INSIDE,
    FIELD_OUTSIDE,
    FIELD_POWER,
    FIELD_AUTO,
    FIELD_CMD_LOCKOUT,
    FIELD_SENSOR_ON_INDOOR_NOTIFICATIONS,
    STATE_LAST_CHANGE,
)


# ============================================================================
# PetDoorSwitch Tests
# ============================================================================

class TestPetDoorSwitch:
    """Tests for PetDoorSwitch entity."""

    @pytest.fixture
    def mock_coordinator(self):
        """Create a mock coordinator with settings data."""
        coordinator = MagicMock(spec=DataUpdateCoordinator)
        coordinator.data = {
            FIELD_INSIDE: True,
            FIELD_OUTSIDE: True,
            FIELD_POWER: True,
            FIELD_AUTO: False,
            FIELD_CMD_LOCKOUT: False,
        }
        coordinator.async_set_updated_data = MagicMock()
        return coordinator

    @pytest.fixture
    def mock_client(self):
        """Create a mock client."""
        client = MagicMock()
        client.host = "192.168.1.100"
        client.port = 3000
        client.available = True
        client.add_listener = MagicMock()
        client.send_message = MagicMock()
        return client

    @pytest.fixture
    def inside_switch(self, mock_client, mock_coordinator):
        """Create an inside sensor switch for testing."""
        switch = PetDoorSwitch(
            client=mock_client,
            name="Test Inside Sensor",
            switch=SWITCHES["inside"],
            coordinator=mock_coordinator,
            device=None
        )
        switch.power = True
        return switch

    @pytest.fixture
    def power_switch(self, mock_client, mock_coordinator):
        """Create a power switch for testing."""
        switch = PetDoorSwitch(
            client=mock_client,
            name="Test Power",
            switch=SWITCHES["power"],
            coordinator=mock_coordinator,
            device=None
        )
        switch.power = True
        return switch

    @pytest.fixture
    def inverted_switch(self, mock_client, mock_coordinator):
        """Create an inverted switch (cmd_lockout) for testing."""
        switch = PetDoorSwitch(
            client=mock_client,
            name="Test Pet Proximity",
            switch=SWITCHES["cmd_lockout"],
            coordinator=mock_coordinator,
            device=None
        )
        switch.power = True
        return switch

    # ==========================================================================
    # State Tests
    # ==========================================================================

    def test_is_on_true(self, inside_switch, mock_coordinator):
        """Test is_on returns True when field is true."""
        mock_coordinator.data[FIELD_INSIDE] = True
        assert inside_switch.is_on is True

    def test_is_on_false(self, inside_switch, mock_coordinator):
        """Test is_on returns False when field is false."""
        mock_coordinator.data[FIELD_INSIDE] = False
        assert inside_switch.is_on is False

    def test_is_on_none_when_no_data(self, inside_switch, mock_coordinator):
        """Test is_on returns None when no data."""
        mock_coordinator.data = None
        assert inside_switch.is_on is None

    def test_is_on_inverted(self, inverted_switch, mock_coordinator):
        """Test inverted switch returns opposite value."""
        mock_coordinator.data[FIELD_CMD_LOCKOUT] = False
        assert inverted_switch.is_on is True  # Inverted, so False becomes True

        mock_coordinator.data[FIELD_CMD_LOCKOUT] = True
        assert inverted_switch.is_on is False  # Inverted, so True becomes False

    def test_is_on_handles_string_true(self, inside_switch, mock_coordinator):
        """Test is_on handles string 'true'."""
        mock_coordinator.data[FIELD_INSIDE] = "true"
        assert inside_switch.is_on is True

    def test_is_on_handles_string_false(self, inside_switch, mock_coordinator):
        """Test is_on handles string 'false'."""
        mock_coordinator.data[FIELD_INSIDE] = "false"
        assert inside_switch.is_on is False

    # ==========================================================================
    # Icon Tests
    # ==========================================================================

    def test_icon_when_on(self, inside_switch, mock_coordinator):
        """Test icon when switch is on."""
        mock_coordinator.data[FIELD_INSIDE] = True
        assert inside_switch.icon == "mdi:leak"

    def test_icon_when_off(self, inside_switch, mock_coordinator):
        """Test icon when switch is off."""
        mock_coordinator.data[FIELD_INSIDE] = False
        assert inside_switch.icon == "mdi:leak-off"

    # ==========================================================================
    # Command Tests
    # ==========================================================================

    @pytest.mark.asyncio
    async def test_turn_on_normal_switch(self, inside_switch, mock_client):
        """Test turning on a normal switch sends enable command."""
        await inside_switch.async_turn_on()
        mock_client.send_message.assert_called_once_with(CONFIG, CMD_ENABLE_INSIDE)

    @pytest.mark.asyncio
    async def test_turn_off_normal_switch(self, inside_switch, mock_client):
        """Test turning off a normal switch sends disable command."""
        await inside_switch.async_turn_off()
        mock_client.send_message.assert_called_once_with(CONFIG, CMD_DISABLE_INSIDE)

    @pytest.mark.asyncio
    async def test_turn_on_inverted_switch(self, inverted_switch, mock_client):
        """Test turning on inverted switch sends disable command."""
        await inverted_switch.async_turn_on()
        # Inverted: turn_on sends disable
        mock_client.send_message.assert_called_once_with(CONFIG, CMD_DISABLE_CMD_LOCKOUT)

    @pytest.mark.asyncio
    async def test_turn_off_inverted_switch(self, inverted_switch, mock_client):
        """Test turning off inverted switch sends enable command."""
        await inverted_switch.async_turn_off()
        # Inverted: turn_off sends enable
        mock_client.send_message.assert_called_once_with(CONFIG, CMD_ENABLE_CMD_LOCKOUT)

    @pytest.mark.asyncio
    async def test_power_on(self, power_switch, mock_client):
        """Test power on sends POWER_ON command."""
        await power_switch.async_turn_on()
        mock_client.send_message.assert_called_once_with(CONFIG, CMD_POWER_ON)

    @pytest.mark.asyncio
    async def test_power_off(self, power_switch, mock_client):
        """Test power off sends POWER_OFF command."""
        await power_switch.async_turn_off()
        mock_client.send_message.assert_called_once_with(CONFIG, CMD_POWER_OFF)

    # ==========================================================================
    # Availability Tests
    # ==========================================================================

    def test_available_when_connected(self, inside_switch, mock_client, mock_coordinator):
        """Test available when client connected."""
        mock_client.available = True
        inside_switch.power = True
        with patch.object(type(inside_switch).__bases__[0], 'available', True):
            assert inside_switch.available is True

    def test_unavailable_when_disconnected(self, inside_switch, mock_client, mock_coordinator):
        """Test unavailable when client disconnected."""
        mock_client.available = False
        inside_switch.power = True
        with patch.object(type(inside_switch).__bases__[0], 'available', True):
            assert inside_switch.available is False

    def test_unavailable_when_power_off(self, inside_switch, mock_client, mock_coordinator):
        """Test unavailable when power is off."""
        mock_client.available = True
        inside_switch.power = False
        with patch.object(type(inside_switch).__bases__[0], 'available', True):
            assert inside_switch.available is False

    # ==========================================================================
    # Callback Tests
    # ==========================================================================

    def test_handle_state_update(self, inside_switch, mock_coordinator):
        """Test state update changes coordinator data."""
        mock_coordinator.data = {FIELD_INSIDE: True, FIELD_POWER: True}
        inside_switch.handle_state_update(False)
        mock_coordinator.async_set_updated_data.assert_called_once()
        call_args = mock_coordinator.async_set_updated_data.call_args[0][0]
        assert call_args[FIELD_INSIDE] is False

    def test_handle_power_update(self, inside_switch):
        """Test power update changes power state."""
        inside_switch.power = True
        inside_switch.async_schedule_update_ha_state = MagicMock()
        inside_switch.handle_power_update(False)
        assert inside_switch.power is False
        inside_switch.async_schedule_update_ha_state.assert_called_once()

    # ==========================================================================
    # Extra Attributes Tests
    # ==========================================================================

    def test_extra_attributes_includes_last_change(self, inside_switch):
        """Test extra attributes includes last change."""
        inside_switch.last_change = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        attrs = inside_switch.extra_state_attributes
        assert STATE_LAST_CHANGE in attrs

    def test_extra_attributes_none_without_last_change(self, inside_switch):
        """Test extra attributes is None without last change."""
        inside_switch.last_change = None
        attrs = inside_switch.extra_state_attributes
        assert attrs is None


# ============================================================================
# PetDoorNotificationSwitch Tests
# ============================================================================

class TestPetDoorNotificationSwitch:
    """Tests for PetDoorNotificationSwitch entity."""

    @pytest.fixture
    def mock_coordinator(self):
        """Create a mock coordinator with notification data."""
        coordinator = MagicMock(spec=DataUpdateCoordinator)
        coordinator.data = {
            FIELD_SENSOR_ON_INDOOR_NOTIFICATIONS: True,
        }
        coordinator.async_set_updated_data = MagicMock()
        return coordinator

    @pytest.fixture
    def mock_client(self):
        """Create a mock client."""
        client = MagicMock()
        client.host = "192.168.1.100"
        client.port = 3000
        client.available = True
        client.add_listener = MagicMock()
        client.send_message = MagicMock()
        return client

    @pytest.fixture
    def notification_switch(self, mock_client, mock_coordinator):
        """Create a notification switch for testing."""
        switch = PetDoorNotificationSwitch(
            client=mock_client,
            name="Test Inside On Notify",
            switch=NOTIFICATION_SWITCHES["inside_on"],
            coordinator=mock_coordinator,
            device=None
        )
        switch.power = True
        return switch

    def test_is_on_true(self, notification_switch, mock_coordinator):
        """Test is_on returns True when notification enabled."""
        mock_coordinator.data[FIELD_SENSOR_ON_INDOOR_NOTIFICATIONS] = True
        assert notification_switch.is_on is True

    def test_is_on_false(self, notification_switch, mock_coordinator):
        """Test is_on returns False when notification disabled."""
        mock_coordinator.data[FIELD_SENSOR_ON_INDOOR_NOTIFICATIONS] = False
        assert notification_switch.is_on is False

    @pytest.mark.asyncio
    async def test_turn_on_sends_notifications(self, notification_switch, mock_client, mock_coordinator):
        """Test turning on sends SET_NOTIFICATIONS with updated data."""
        mock_coordinator.data = {FIELD_SENSOR_ON_INDOOR_NOTIFICATIONS: False}
        await notification_switch.async_turn_on()
        mock_client.send_message.assert_called_once()
        call_args = mock_client.send_message.call_args
        assert call_args[0][0] == CONFIG
        assert call_args[0][1] == CMD_SET_NOTIFICATIONS
        assert call_args[1]["notifications"][FIELD_SENSOR_ON_INDOOR_NOTIFICATIONS] is True

    @pytest.mark.asyncio
    async def test_turn_off_sends_notifications(self, notification_switch, mock_client, mock_coordinator):
        """Test turning off sends SET_NOTIFICATIONS with updated data."""
        mock_coordinator.data = {FIELD_SENSOR_ON_INDOOR_NOTIFICATIONS: True}
        await notification_switch.async_turn_off()
        mock_client.send_message.assert_called_once()
        call_args = mock_client.send_message.call_args
        assert call_args[1]["notifications"][FIELD_SENSOR_ON_INDOOR_NOTIFICATIONS] is False


# ============================================================================
# ConnectionSwitch Tests
# ============================================================================

class TestConnectionSwitch:
    """Tests for ConnectionSwitch entity."""

    @pytest.fixture
    def mock_coordinator(self):
        """Create a mock coordinator."""
        coordinator = MagicMock(spec=DataUpdateCoordinator)
        coordinator.data = {}
        return coordinator

    @pytest.fixture
    def mock_client(self):
        """Create a mock client."""
        client = MagicMock()
        client.host = "192.168.1.100"
        client.port = 3000
        client.available = False
        client.add_handlers = MagicMock()
        client.start = MagicMock()
        client.stop = MagicMock()
        return client

    @pytest.fixture
    def connection_switch(self, mock_client, mock_coordinator):
        """Create a connection switch for testing."""
        switch = ConnectionSwitch(
            client=mock_client,
            name="Test Connection",
            coordinator=mock_coordinator,
            device=None
        )
        return switch

    # ==========================================================================
    # State Tests
    # ==========================================================================

    def test_default_desired_on(self, connection_switch):
        """Test default desired state is on."""
        assert connection_switch._desired_on is True

    def test_is_on_returns_desired_state(self, connection_switch):
        """Test is_on returns desired state, not actual connection state."""
        connection_switch._desired_on = True
        assert connection_switch.is_on is True

        connection_switch._desired_on = False
        assert connection_switch.is_on is False

    def test_always_available(self, connection_switch, mock_client):
        """Test connection switch is always available."""
        mock_client.available = False
        assert connection_switch.available is True

        mock_client.available = True
        assert connection_switch.available is True

    # ==========================================================================
    # Command Tests
    # ==========================================================================

    @pytest.mark.asyncio
    async def test_turn_on_calls_start(self, connection_switch, mock_client):
        """Test turning on calls client.start()."""
        connection_switch._desired_on = False
        connection_switch.async_write_ha_state = MagicMock()
        await connection_switch.async_turn_on()

        assert connection_switch._desired_on is True
        mock_client.start.assert_called_once()
        connection_switch.async_write_ha_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_turn_off_calls_stop(self, connection_switch, mock_client):
        """Test turning off calls client.stop()."""
        connection_switch._desired_on = True
        connection_switch.async_write_ha_state = MagicMock()
        await connection_switch.async_turn_off()

        assert connection_switch._desired_on is False
        mock_client.stop.assert_called_once()
        connection_switch.async_write_ha_state.assert_called_once()

    # ==========================================================================
    # Extra Attributes Tests
    # ==========================================================================

    def test_extra_attributes_shows_connected_status(self, connection_switch, mock_client):
        """Test extra attributes shows actual connection status."""
        mock_client.available = True
        attrs = connection_switch.extra_state_attributes
        assert attrs["connected"] is True

        mock_client.available = False
        attrs = connection_switch.extra_state_attributes
        assert attrs["connected"] is False

    # ==========================================================================
    # Lifecycle Tests
    # ==========================================================================

    @pytest.mark.asyncio
    async def test_added_to_hass_starts_client(self, connection_switch, mock_client):
        """Test adding to hass starts the client."""
        with patch.object(type(connection_switch).__bases__[0], 'async_added_to_hass', new_callable=AsyncMock):
            await connection_switch.async_added_to_hass()

        assert connection_switch._desired_on is True
        mock_client.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_will_remove_stops_client(self, connection_switch, mock_client):
        """Test removing from hass stops the client."""
        with patch.object(type(connection_switch).__bases__[0], 'async_will_remove_from_hass', new_callable=AsyncMock):
            await connection_switch.async_will_remove_from_hass()

        mock_client.stop.assert_called_once()

    # ==========================================================================
    # Callback Tests
    # ==========================================================================

    @pytest.mark.asyncio
    async def test_handle_connect_updates_state(self, connection_switch):
        """Test handle_connect updates HA state."""
        connection_switch.async_write_ha_state = MagicMock()
        await connection_switch._handle_connect()
        connection_switch.async_write_ha_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_disconnect_updates_state(self, connection_switch):
        """Test handle_disconnect updates HA state."""
        connection_switch.async_write_ha_state = MagicMock()
        await connection_switch._handle_disconnect()
        connection_switch.async_write_ha_state.assert_called_once()


# ============================================================================
# Switch Configuration Tests
# ============================================================================

class TestSwitchConfiguration:
    """Tests for switch configuration dictionaries."""

    def test_switches_have_required_fields(self):
        """Test all switches have required fields."""
        for name, switch in SWITCHES.items():
            assert "field" in switch, f"{name} missing 'field'"
            assert "update" in switch, f"{name} missing 'update'"
            assert "enable" in switch, f"{name} missing 'enable'"
            assert "disable" in switch, f"{name} missing 'disable'"
            assert "icon_on" in switch, f"{name} missing 'icon_on'"
            assert "icon_off" in switch, f"{name} missing 'icon_off'"

    def test_notification_switches_have_required_fields(self):
        """Test all notification switches have required fields."""
        for name, switch in NOTIFICATION_SWITCHES.items():
            assert "field" in switch, f"{name} missing 'field'"
            assert "icon_on" in switch, f"{name} missing 'icon_on'"
            assert "icon_off" in switch, f"{name} missing 'icon_off'"

    def test_inside_switch_config(self):
        """Test inside switch configuration."""
        switch = SWITCHES["inside"]
        assert switch["field"] == FIELD_INSIDE
        assert switch["enable"] == CMD_ENABLE_INSIDE
        assert switch["disable"] == CMD_DISABLE_INSIDE
        assert switch["category"] == EntityCategory.CONFIG

    def test_power_switch_has_no_category(self):
        """Test power switch has no entity category."""
        switch = SWITCHES["power"]
        assert "category" not in switch

    def test_cmd_lockout_is_inverted(self):
        """Test cmd_lockout switch is inverted."""
        switch = SWITCHES["cmd_lockout"]
        assert switch.get("inverted") is True
