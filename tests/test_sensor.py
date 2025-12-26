# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""Tests for Power Pet Door sensor entities."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Skip all tests in this module if Home Assistant is not available
pytest.importorskip("homeassistant")
pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.core import HomeAssistant
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import EntityCategory, UnitOfTime, PERCENTAGE
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from custom_components.powerpetdoor.sensor import (
    PetDoorLatency,
    PetDoorBattery,
    PetDoorStats,
    STATS,
)
from custom_components.powerpetdoor.const import (
    CONF_HOST,
    CONF_PORT,
    STATE_LAST_CHANGE,
    STATE_BATTERY_CHARGING,
    STATE_BATTERY_DISCHARGING,
    FIELD_BATTERY_PERCENT,
    FIELD_BATTERY_PRESENT,
    FIELD_AC_PRESENT,
    FIELD_POWER,
    FIELD_TOTAL_OPEN_CYCLES,
    FIELD_FW_VER,
    FIELD_FW_REV,
    FIELD_FW_MAJOR,
    FIELD_FW_MINOR,
    FIELD_FW_PATCH,
)


# ============================================================================
# PetDoorLatency Tests
# ============================================================================

class TestPetDoorLatency:
    """Tests for PetDoorLatency sensor entity."""

    @pytest.fixture
    def mock_coordinator(self, hass: HomeAssistant):
        """Create a mock coordinator."""
        coordinator = MagicMock(spec=DataUpdateCoordinator)
        coordinator.data = {
            FIELD_FW_VER: "1.0",
            FIELD_FW_REV: "A",
            FIELD_FW_MAJOR: 2,
            FIELD_FW_MINOR: 5,
            FIELD_FW_PATCH: 0,
        }
        coordinator.async_request_refresh = AsyncMock()
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
        client.add_handlers = MagicMock()
        client.send_message = MagicMock(return_value=asyncio.Future())
        return client

    @pytest.fixture
    def latency_sensor(self, hass: HomeAssistant, mock_client, mock_coordinator):
        """Create a latency sensor for testing."""
        with patch.object(PetDoorLatency, '__init__', lambda self, **kwargs: None):
            sensor = PetDoorLatency.__new__(PetDoorLatency)
            sensor.hass = hass
            sensor.client = mock_client
            sensor.coordinator = mock_coordinator
            sensor.last_change = None
            sensor._attr_name = "Test Latency"
            sensor._attr_unique_id = "192.168.1.100:3000-latency"
            sensor._attr_device_info = {}
            sensor._attr_native_value = None
            return sensor

    # ==========================================================================
    # Entity Properties Tests
    # ==========================================================================

    def test_entity_category_is_diagnostic(self, latency_sensor):
        """Test entity category is diagnostic."""
        assert latency_sensor.entity_category == EntityCategory.DIAGNOSTIC

    def test_state_class_is_measurement(self, latency_sensor):
        """Test state class is measurement."""
        assert latency_sensor.state_class == SensorStateClass.MEASUREMENT

    def test_unit_is_milliseconds(self, latency_sensor):
        """Test unit is milliseconds."""
        assert latency_sensor.native_unit_of_measurement == UnitOfTime.MILLISECONDS

    # ==========================================================================
    # Icon Tests
    # ==========================================================================

    def test_icon_when_connected(self, latency_sensor, mock_client, mock_coordinator):
        """Test icon when connected and data available."""
        mock_client.available = True
        with patch.object(type(latency_sensor).__bases__[0], 'available', True):
            assert latency_sensor.icon == "mdi:lan-connect"

    def test_icon_when_connected_pending(self, latency_sensor, mock_client, mock_coordinator):
        """Test icon when connected but no data."""
        mock_client.available = True
        with patch.object(type(latency_sensor).__bases__[0], 'available', False):
            assert latency_sensor.icon == "mdi:lan-pending"

    def test_icon_when_disconnected(self, latency_sensor, mock_client):
        """Test icon when disconnected."""
        mock_client.available = False
        assert latency_sensor.icon == "mdi:lan-disconnect"

    # ==========================================================================
    # Ping Callback Tests
    # ==========================================================================

    def test_on_ping_sets_native_value(self, latency_sensor):
        """Test on_ping sets native value."""
        latency_sensor.async_schedule_update_ha_state = MagicMock()
        latency_sensor.on_ping(150)
        assert latency_sensor._attr_native_value == 150
        latency_sensor.async_schedule_update_ha_state.assert_called_once()

    # ==========================================================================
    # Extra Attributes Tests
    # ==========================================================================

    def test_extra_attributes_includes_host_port(self, latency_sensor, mock_client):
        """Test extra attributes includes host and port."""
        attrs = latency_sensor.extra_state_attributes
        assert attrs[CONF_HOST] == "192.168.1.100"
        assert attrs[CONF_PORT] == 3000

    def test_extra_attributes_includes_last_change(self, latency_sensor):
        """Test extra attributes includes last change when set."""
        latency_sensor.last_change = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        attrs = latency_sensor.extra_state_attributes
        assert STATE_LAST_CHANGE in attrs

    # ==========================================================================
    # Hardware Info Callback Tests
    # ==========================================================================

    def test_handle_hw_info_updates_data(self, latency_sensor, mock_coordinator):
        """Test handle_hw_info updates coordinator when data differs."""
        mock_coordinator.data = {FIELD_FW_VER: "1.0"}
        new_info = {FIELD_FW_VER: "2.0"}
        latency_sensor.handle_hw_info(new_info)
        mock_coordinator.async_set_updated_data.assert_called_once_with(new_info)

    def test_handle_hw_info_ignores_same_data(self, latency_sensor, mock_coordinator):
        """Test handle_hw_info ignores same data."""
        data = {FIELD_FW_VER: "1.0"}
        mock_coordinator.data = data
        latency_sensor.handle_hw_info(data)
        mock_coordinator.async_set_updated_data.assert_not_called()


# ============================================================================
# PetDoorBattery Tests
# ============================================================================

class TestPetDoorBattery:
    """Tests for PetDoorBattery sensor entity."""

    @pytest.fixture
    def mock_coordinator(self, hass: HomeAssistant):
        """Create a mock coordinator with battery data."""
        coordinator = MagicMock(spec=DataUpdateCoordinator)
        coordinator.data = {
            FIELD_BATTERY_PERCENT: 85,
            FIELD_BATTERY_PRESENT: True,
            FIELD_AC_PRESENT: True,
        }
        coordinator.async_request_refresh = AsyncMock()
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
        client.add_handlers = MagicMock()
        client.send_message = MagicMock(return_value=asyncio.Future())
        return client

    @pytest.fixture
    def battery_sensor(self, hass: HomeAssistant, mock_client, mock_coordinator):
        """Create a battery sensor for testing."""
        with patch.object(PetDoorBattery, '__init__', lambda self, **kwargs: None):
            sensor = PetDoorBattery.__new__(PetDoorBattery)
            sensor.hass = hass
            sensor.client = mock_client
            sensor.coordinator = mock_coordinator
            sensor.last_change = None
            sensor._attr_name = "Test Battery"
            sensor._attr_unique_id = "192.168.1.100:3000-battery"
            sensor._attr_device_info = None
            return sensor

    # ==========================================================================
    # Entity Properties Tests
    # ==========================================================================

    def test_device_class_is_battery(self, battery_sensor):
        """Test device class is battery."""
        assert battery_sensor.device_class == SensorDeviceClass.BATTERY

    def test_unit_is_percentage(self, battery_sensor):
        """Test unit is percentage."""
        assert battery_sensor.native_unit_of_measurement == PERCENTAGE

    # ==========================================================================
    # Native Value Tests
    # ==========================================================================

    def test_native_value_returns_percent(self, battery_sensor, mock_coordinator):
        """Test native_value returns battery percentage."""
        mock_coordinator.data = {FIELD_BATTERY_PERCENT: 75}
        assert battery_sensor.native_value == 75

    def test_native_value_none_when_no_data(self, battery_sensor, mock_coordinator):
        """Test native_value returns None when no data."""
        mock_coordinator.data = None
        assert battery_sensor.native_value is None

    # ==========================================================================
    # Battery Present Tests
    # ==========================================================================

    def test_battery_present_true(self, battery_sensor, mock_coordinator):
        """Test battery_present returns True when present."""
        mock_coordinator.data = {FIELD_BATTERY_PRESENT: True}
        assert battery_sensor.battery_present is True

    def test_battery_present_false(self, battery_sensor, mock_coordinator):
        """Test battery_present returns False when not present."""
        mock_coordinator.data = {FIELD_BATTERY_PRESENT: False}
        assert battery_sensor.battery_present is False

    # ==========================================================================
    # AC Present Tests
    # ==========================================================================

    def test_ac_present_true(self, battery_sensor, mock_coordinator):
        """Test ac_present returns True when AC connected."""
        mock_coordinator.data = {FIELD_AC_PRESENT: True}
        assert battery_sensor.ac_present is True

    def test_ac_present_false(self, battery_sensor, mock_coordinator):
        """Test ac_present returns False when AC not connected."""
        mock_coordinator.data = {FIELD_AC_PRESENT: False}
        assert battery_sensor.ac_present is False

    # ==========================================================================
    # Icon Tests (Battery Level)
    # ==========================================================================

    def test_icon_battery_unknown(self, battery_sensor, mock_coordinator):
        """Test icon when battery level unknown."""
        mock_coordinator.data = {FIELD_BATTERY_PERCENT: None, FIELD_BATTERY_PRESENT: True}
        assert battery_sensor.icon == "mdi:battery-unknown"

    def test_icon_battery_not_present(self, battery_sensor, mock_coordinator):
        """Test icon when battery not present."""
        mock_coordinator.data = {
            FIELD_BATTERY_PERCENT: 50,
            FIELD_BATTERY_PRESENT: False,
            FIELD_AC_PRESENT: True,
        }
        assert battery_sensor.icon == "mdi:battery-off-outline"

    def test_icon_battery_low_discharging(self, battery_sensor, mock_coordinator):
        """Test icon when battery low and discharging."""
        mock_coordinator.data = {
            FIELD_BATTERY_PERCENT: 5,
            FIELD_BATTERY_PRESENT: True,
            FIELD_AC_PRESENT: False,
        }
        assert battery_sensor.icon == "mdi:battery-outline"

    def test_icon_battery_low_charging(self, battery_sensor, mock_coordinator):
        """Test icon when battery low and charging."""
        mock_coordinator.data = {
            FIELD_BATTERY_PERCENT: 5,
            FIELD_BATTERY_PRESENT: True,
            FIELD_AC_PRESENT: True,
        }
        assert battery_sensor.icon == "mdi:battery-charging"

    def test_icon_battery_50_discharging(self, battery_sensor, mock_coordinator):
        """Test icon when battery at 50% and discharging."""
        mock_coordinator.data = {
            FIELD_BATTERY_PERCENT: 55,
            FIELD_BATTERY_PRESENT: True,
            FIELD_AC_PRESENT: False,
        }
        assert battery_sensor.icon == "mdi:battery-50"

    def test_icon_battery_50_charging(self, battery_sensor, mock_coordinator):
        """Test icon when battery at 50% and charging."""
        mock_coordinator.data = {
            FIELD_BATTERY_PERCENT: 55,
            FIELD_BATTERY_PRESENT: True,
            FIELD_AC_PRESENT: True,
        }
        assert battery_sensor.icon == "mdi:battery-charging-50"

    def test_icon_battery_full(self, battery_sensor, mock_coordinator):
        """Test icon when battery full."""
        mock_coordinator.data = {
            FIELD_BATTERY_PERCENT: 100,
            FIELD_BATTERY_PRESENT: True,
            FIELD_AC_PRESENT: False,
        }
        assert battery_sensor.icon == "mdi:battery"

    # ==========================================================================
    # Extra Attributes Tests
    # ==========================================================================

    def test_extra_attributes_charging_status(self, battery_sensor, mock_coordinator):
        """Test extra attributes includes charging status."""
        mock_coordinator.data = {
            FIELD_BATTERY_PERCENT: 50,
            FIELD_BATTERY_PRESENT: True,
            FIELD_AC_PRESENT: True,
        }
        with patch.object(type(battery_sensor).__bases__[0], 'available', True):
            attrs = battery_sensor.extra_state_attributes
        assert attrs[STATE_BATTERY_CHARGING] is True
        assert attrs[STATE_BATTERY_DISCHARGING] is False

    def test_extra_attributes_discharging_status(self, battery_sensor, mock_coordinator):
        """Test extra attributes shows discharging when AC not present."""
        mock_coordinator.data = {
            FIELD_BATTERY_PERCENT: 50,
            FIELD_BATTERY_PRESENT: True,
            FIELD_AC_PRESENT: False,
        }
        with patch.object(type(battery_sensor).__bases__[0], 'available', True):
            attrs = battery_sensor.extra_state_attributes
        assert attrs[STATE_BATTERY_CHARGING] is False
        assert attrs[STATE_BATTERY_DISCHARGING] is True

    def test_extra_attributes_not_charging_when_full(self, battery_sensor, mock_coordinator):
        """Test extra attributes shows not charging when battery full."""
        mock_coordinator.data = {
            FIELD_BATTERY_PERCENT: 100,
            FIELD_BATTERY_PRESENT: True,
            FIELD_AC_PRESENT: True,
        }
        with patch.object(type(battery_sensor).__bases__[0], 'available', True):
            attrs = battery_sensor.extra_state_attributes
        assert attrs[STATE_BATTERY_CHARGING] is False

    # ==========================================================================
    # Callback Tests
    # ==========================================================================

    def test_handle_battery_update(self, battery_sensor, mock_coordinator):
        """Test handle_battery_update updates coordinator."""
        old_data = {FIELD_BATTERY_PERCENT: 50}
        new_data = {FIELD_BATTERY_PERCENT: 60}
        mock_coordinator.data = old_data
        battery_sensor.handle_battery_update(new_data)
        mock_coordinator.async_set_updated_data.assert_called_once_with(new_data)

    def test_handle_battery_update_ignores_same(self, battery_sensor, mock_coordinator):
        """Test handle_battery_update ignores same data."""
        data = {FIELD_BATTERY_PERCENT: 50}
        mock_coordinator.data = data
        battery_sensor.handle_battery_update(data)
        mock_coordinator.async_set_updated_data.assert_not_called()


# ============================================================================
# PetDoorStats Tests
# ============================================================================

class TestPetDoorStats:
    """Tests for PetDoorStats sensor entity."""

    @pytest.fixture
    def mock_coordinator(self):
        """Create a mock coordinator with stats data."""
        coordinator = MagicMock(spec=DataUpdateCoordinator)
        coordinator.data = {
            FIELD_TOTAL_OPEN_CYCLES: 1234,
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
        return client

    @pytest.fixture
    def stats_sensor(self, mock_client, mock_coordinator):
        """Create a stats sensor for testing."""
        sensor = PetDoorStats(
            client=mock_client,
            name="Test Open Cycles",
            sensor=STATS["open_cycles"],
            coordinator=mock_coordinator,
            device=None
        )
        sensor.power = True
        return sensor

    # ==========================================================================
    # Native Value Tests
    # ==========================================================================

    def test_native_value_returns_count(self, stats_sensor, mock_coordinator):
        """Test native_value returns stat count."""
        mock_coordinator.data = {FIELD_TOTAL_OPEN_CYCLES: 500}
        assert stats_sensor.native_value == 500

    def test_native_value_none_when_no_data(self, stats_sensor, mock_coordinator):
        """Test native_value returns None when no data."""
        mock_coordinator.data = None
        assert stats_sensor.native_value is None

    # ==========================================================================
    # Availability Tests
    # ==========================================================================

    def test_available_when_connected(self, stats_sensor, mock_client, mock_coordinator):
        """Test available when client connected."""
        mock_client.available = True
        stats_sensor.power = True
        with patch.object(type(stats_sensor).__bases__[0], 'available', True):
            assert stats_sensor.available is True

    def test_unavailable_when_power_off(self, stats_sensor, mock_client, mock_coordinator):
        """Test unavailable when power off."""
        mock_client.available = True
        stats_sensor.power = False
        with patch.object(type(stats_sensor).__bases__[0], 'available', True):
            assert stats_sensor.available is False

    # ==========================================================================
    # Callback Tests
    # ==========================================================================

    def test_handle_state_update(self, stats_sensor, mock_coordinator):
        """Test handle_state_update updates coordinator."""
        mock_coordinator.data = {FIELD_TOTAL_OPEN_CYCLES: 100}
        stats_sensor.handle_state_update(200)
        mock_coordinator.async_set_updated_data.assert_called_once()
        call_args = mock_coordinator.async_set_updated_data.call_args[0][0]
        assert call_args[FIELD_TOTAL_OPEN_CYCLES] == 200

    def test_handle_power_update(self, stats_sensor):
        """Test handle_power_update updates power state."""
        stats_sensor.power = True
        stats_sensor.async_schedule_update_ha_state = MagicMock()
        stats_sensor.handle_power_update(False)
        assert stats_sensor.power is False
        stats_sensor.async_schedule_update_ha_state.assert_called_once()


# ============================================================================
# Stats Configuration Tests
# ============================================================================

class TestStatsConfiguration:
    """Tests for stats sensor configuration."""

    def test_open_cycles_config(self):
        """Test open cycles sensor configuration."""
        sensor = STATS["open_cycles"]
        assert sensor["field"] == FIELD_TOTAL_OPEN_CYCLES
        assert sensor["icon"] == "mdi:reload"
        assert sensor["class"] == "total_increasing"
        assert sensor["category"] == EntityCategory.DIAGNOSTIC
        assert sensor["disabled"] is True

    def test_auto_retracts_config(self):
        """Test auto retracts sensor configuration."""
        sensor = STATS["auto_retracts"]
        assert sensor["icon"] == "mdi:alert"
        assert sensor["class"] == "total_increasing"
        assert sensor["disabled"] is True
