# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""Tests for Power Pet Door cover entity."""
from __future__ import annotations

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Skip all tests in this module if Home Assistant is not available
pytest.importorskip("homeassistant")
pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.core import HomeAssistant
from homeassistant.components.cover import CoverDeviceClass, CoverEntityFeature
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from custom_components.powerpetdoor.cover import PetDoor
from custom_components.powerpetdoor.const import (
    COMMAND,
    CONFIG,
    CMD_GET_DOOR_STATUS,
    CMD_OPEN_AND_HOLD,
    CMD_CLOSE,
    DOOR_STATE_IDLE,
    DOOR_STATE_CLOSED,
    DOOR_STATE_HOLDING,
    DOOR_STATE_KEEPUP,
    DOOR_STATE_SLOWING,
    DOOR_STATE_RISING,
    DOOR_STATE_CLOSING_TOP_OPEN,
    DOOR_STATE_CLOSING_MID_OPEN,
    FIELD_DOOR_STATUS,
    STATE_LAST_CHANGE,
)


class TestPetDoorEntity:
    """Tests for the PetDoor cover entity."""

    @pytest.fixture
    def mock_coordinator(self, hass: HomeAssistant):
        """Create a mock coordinator."""
        coordinator = MagicMock(spec=DataUpdateCoordinator)
        coordinator.data = DOOR_STATE_CLOSED
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
    def pet_door(self, hass: HomeAssistant, mock_client, mock_coordinator):
        """Create a PetDoor entity for testing."""
        with patch.object(PetDoor, '__init__', lambda self, **kwargs: None):
            door = PetDoor.__new__(PetDoor)
            door.client = mock_client
            door.coordinator = mock_coordinator
            door.last_change = None
            door.power = True
            door._attr_name = "Test Door"
            door._attr_unique_id = "192.168.1.100:3000-door"
            door._attr_device_info = None
            return door

    # ==========================================================================
    # Cover State Tests
    # ==========================================================================

    def test_is_closed_when_idle(self, pet_door, mock_coordinator):
        """Test door is closed when state is IDLE."""
        mock_coordinator.data = DOOR_STATE_IDLE
        assert pet_door.is_closed is True

    def test_is_closed_when_closed(self, pet_door, mock_coordinator):
        """Test door is closed when state is CLOSED."""
        mock_coordinator.data = DOOR_STATE_CLOSED
        assert pet_door.is_closed is True

    def test_is_closed_when_holding(self, pet_door, mock_coordinator):
        """Test door is not closed when state is HOLDING."""
        mock_coordinator.data = DOOR_STATE_HOLDING
        assert pet_door.is_closed is False

    def test_is_closed_when_keepup(self, pet_door, mock_coordinator):
        """Test door is not closed when state is KEEPUP."""
        mock_coordinator.data = DOOR_STATE_KEEPUP
        assert pet_door.is_closed is False

    def test_is_closed_returns_none_when_no_data(self, pet_door, mock_coordinator):
        """Test is_closed returns None when no data."""
        mock_coordinator.data = None
        assert pet_door.is_closed is None

    # ==========================================================================
    # Opening State Tests
    # ==========================================================================

    def test_is_opening_when_rising(self, pet_door, mock_coordinator):
        """Test door is opening when state is RISING."""
        mock_coordinator.data = DOOR_STATE_RISING
        assert pet_door.is_opening is True

    def test_is_opening_when_slowing(self, pet_door, mock_coordinator):
        """Test door is opening when state is SLOWING."""
        mock_coordinator.data = DOOR_STATE_SLOWING
        assert pet_door.is_opening is True

    def test_is_opening_when_closed(self, pet_door, mock_coordinator):
        """Test door is not opening when closed."""
        mock_coordinator.data = DOOR_STATE_CLOSED
        assert pet_door.is_opening is False

    def test_is_opening_returns_none_when_no_data(self, pet_door, mock_coordinator):
        """Test is_opening returns None when no data."""
        mock_coordinator.data = None
        assert pet_door.is_opening is None

    # ==========================================================================
    # Closing State Tests
    # ==========================================================================

    def test_is_closing_when_closing_top(self, pet_door, mock_coordinator):
        """Test door is closing when state is CLOSING_TOP_OPEN."""
        mock_coordinator.data = DOOR_STATE_CLOSING_TOP_OPEN
        assert pet_door.is_closing is True

    def test_is_closing_when_closing_mid(self, pet_door, mock_coordinator):
        """Test door is closing when state is CLOSING_MID_OPEN."""
        mock_coordinator.data = DOOR_STATE_CLOSING_MID_OPEN
        assert pet_door.is_closing is True

    def test_is_closing_when_open(self, pet_door, mock_coordinator):
        """Test door is not closing when open."""
        mock_coordinator.data = DOOR_STATE_KEEPUP
        assert pet_door.is_closing is False

    def test_is_closing_returns_none_when_no_data(self, pet_door, mock_coordinator):
        """Test is_closing returns None when no data."""
        mock_coordinator.data = None
        assert pet_door.is_closing is None

    # ==========================================================================
    # Position Tests
    # ==========================================================================

    def test_position_0_when_closed(self, pet_door, mock_coordinator):
        """Test position is 0 when door is closed."""
        mock_coordinator.data = DOOR_STATE_CLOSED
        assert pet_door.current_cover_position == 0

    def test_position_0_when_idle(self, pet_door, mock_coordinator):
        """Test position is 0 when door is idle."""
        mock_coordinator.data = DOOR_STATE_IDLE
        assert pet_door.current_cover_position == 0

    def test_position_100_when_holding(self, pet_door, mock_coordinator):
        """Test position is 100 when door is holding."""
        mock_coordinator.data = DOOR_STATE_HOLDING
        assert pet_door.current_cover_position == 100

    def test_position_100_when_keepup(self, pet_door, mock_coordinator):
        """Test position is 100 when door is keep up."""
        mock_coordinator.data = DOOR_STATE_KEEPUP
        assert pet_door.current_cover_position == 100

    def test_position_66_when_slowing(self, pet_door, mock_coordinator):
        """Test position is 66 when door is slowing."""
        mock_coordinator.data = DOOR_STATE_SLOWING
        assert pet_door.current_cover_position == 66

    def test_position_66_when_closing_top(self, pet_door, mock_coordinator):
        """Test position is 66 when door is closing from top."""
        mock_coordinator.data = DOOR_STATE_CLOSING_TOP_OPEN
        assert pet_door.current_cover_position == 66

    def test_position_33_when_rising(self, pet_door, mock_coordinator):
        """Test position is 33 when door is rising."""
        mock_coordinator.data = DOOR_STATE_RISING
        assert pet_door.current_cover_position == 33

    def test_position_33_when_closing_mid(self, pet_door, mock_coordinator):
        """Test position is 33 when door is closing from mid."""
        mock_coordinator.data = DOOR_STATE_CLOSING_MID_OPEN
        assert pet_door.current_cover_position == 33

    def test_position_none_when_no_data(self, pet_door, mock_coordinator):
        """Test position is None when no data."""
        mock_coordinator.data = None
        assert pet_door.current_cover_position is None

    # ==========================================================================
    # Availability Tests
    # ==========================================================================

    def test_available_when_connected_and_powered(self, pet_door, mock_client, mock_coordinator):
        """Test available when client connected and power on."""
        mock_client.available = True
        pet_door.power = True
        mock_coordinator.last_update_success = True
        # CoordinatorEntity.available checks coordinator state
        with patch.object(type(pet_door).__bases__[0], 'available', True):
            assert pet_door.available is True

    def test_unavailable_when_disconnected(self, pet_door, mock_client, mock_coordinator):
        """Test unavailable when client disconnected."""
        mock_client.available = False
        pet_door.power = True
        with patch.object(type(pet_door).__bases__[0], 'available', True):
            assert pet_door.available is False

    def test_unavailable_when_power_off(self, pet_door, mock_client, mock_coordinator):
        """Test unavailable when power is off."""
        mock_client.available = True
        pet_door.power = False
        with patch.object(type(pet_door).__bases__[0], 'available', True):
            assert pet_door.available is False

    # ==========================================================================
    # Command Tests
    # ==========================================================================

    @pytest.mark.asyncio
    async def test_open_cover_sends_command(self, pet_door, mock_client):
        """Test opening cover sends OPEN_AND_HOLD command."""
        await pet_door.async_open_cover()
        mock_client.send_message.assert_called_once_with(COMMAND, CMD_OPEN_AND_HOLD)

    @pytest.mark.asyncio
    async def test_close_cover_sends_command(self, pet_door, mock_client):
        """Test closing cover sends CLOSE command."""
        await pet_door.async_close_cover()
        mock_client.send_message.assert_called_once_with(COMMAND, CMD_CLOSE)

    @pytest.mark.asyncio
    async def test_toggle_opens_when_closed(self, pet_door, mock_client, mock_coordinator):
        """Test toggle opens door when closed."""
        mock_coordinator.data = DOOR_STATE_CLOSED
        await pet_door.async_toggle()
        mock_client.send_message.assert_called_once_with(COMMAND, CMD_OPEN_AND_HOLD)

    @pytest.mark.asyncio
    async def test_toggle_closes_when_open(self, pet_door, mock_client, mock_coordinator):
        """Test toggle closes door when open."""
        mock_coordinator.data = DOOR_STATE_HOLDING
        await pet_door.async_toggle()
        mock_client.send_message.assert_called_once_with(COMMAND, CMD_CLOSE)

    # ==========================================================================
    # Extra Attributes Tests
    # ==========================================================================

    def test_extra_attributes_includes_door_status(self, pet_door, mock_coordinator):
        """Test extra attributes includes door status."""
        mock_coordinator.data = DOOR_STATE_HOLDING
        attrs = pet_door.extra_state_attributes
        assert FIELD_DOOR_STATUS in attrs
        assert attrs[FIELD_DOOR_STATUS] == DOOR_STATE_HOLDING

    def test_extra_attributes_includes_last_change(self, pet_door, mock_coordinator):
        """Test extra attributes includes last change when set."""
        from datetime import datetime, timezone
        pet_door.last_change = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        mock_coordinator.data = DOOR_STATE_CLOSED
        attrs = pet_door.extra_state_attributes
        assert STATE_LAST_CHANGE in attrs
        assert "2025-01-15" in attrs[STATE_LAST_CHANGE]

    def test_extra_attributes_empty_when_no_data(self, pet_door, mock_coordinator):
        """Test extra attributes empty when no data."""
        mock_coordinator.data = None
        pet_door.last_change = None
        attrs = pet_door.extra_state_attributes
        assert attrs == {}

    # ==========================================================================
    # Entity Properties Tests
    # ==========================================================================

    def test_device_class(self, pet_door):
        """Test device class is SHUTTER."""
        assert pet_door.device_class == CoverDeviceClass.SHUTTER

    def test_supported_features(self, pet_door):
        """Test supported features are OPEN and CLOSE."""
        expected = CoverEntityFeature.CLOSE | CoverEntityFeature.OPEN
        assert pet_door.supported_features == expected

    # ==========================================================================
    # State Update Tests
    # ==========================================================================

    def test_handle_state_update_changes_data(self, pet_door, mock_coordinator):
        """Test handle_state_update updates coordinator data."""
        mock_coordinator.data = DOOR_STATE_CLOSED
        pet_door.handle_state_update(DOOR_STATE_HOLDING)
        mock_coordinator.async_set_updated_data.assert_called_once_with(DOOR_STATE_HOLDING)

    def test_handle_state_update_ignores_same_state(self, pet_door, mock_coordinator):
        """Test handle_state_update ignores same state."""
        mock_coordinator.data = DOOR_STATE_CLOSED
        pet_door.handle_state_update(DOOR_STATE_CLOSED)
        mock_coordinator.async_set_updated_data.assert_not_called()

    def test_handle_power_update_sets_power(self, pet_door):
        """Test handle_power_update sets power state."""
        pet_door.power = True
        pet_door.async_schedule_update_ha_state = MagicMock()
        pet_door.handle_power_update(False)
        assert pet_door.power is False
        pet_door.async_schedule_update_ha_state.assert_called_once()
