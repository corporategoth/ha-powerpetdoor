# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""Integration tests using the Power Pet Door simulator.

These tests use the real pypowerpetdoor simulator to validate correct behavior
of the client against a simulated door. The simulator can be controlled
programmatically to:
- Trigger spontaneous notifications (sensor triggers, battery events)
- Simulate door state changes
- Verify client behavior under various conditions

NOTE: This test module requires socket access for the simulator's TCP server.
Run with: pytest tests/test_simulator.py --allow-hosts=127.0.0.1,::1
"""
from __future__ import annotations

import asyncio
import logging
import socket

import pytest

# Import from the library
from powerpetdoor import PowerPetDoorClient
from powerpetdoor.const import (
    COMMAND,
    CONFIG,
    DOOR_STATE_CLOSED,
    DOOR_STATE_RISING,
    DOOR_STATE_HOLDING,
    DOOR_STATE_KEEPUP,
    DOOR_STATE_SLOWING,
    DOOR_STATE_CLOSING_TOP_OPEN,
    DOOR_STATE_CLOSING_MID_OPEN,
    CMD_OPEN,
    CMD_OPEN_AND_HOLD,
    CMD_CLOSE,
    CMD_GET_DOOR_STATUS,
    CMD_GET_SETTINGS,
    CMD_GET_DOOR_BATTERY,
    CMD_POWER_ON,
    CMD_POWER_OFF,
    CMD_ENABLE_INSIDE,
    CMD_DISABLE_INSIDE,
    CMD_ENABLE_OUTSIDE,
    CMD_DISABLE_OUTSIDE,
    FIELD_SUCCESS,
    FIELD_DOOR_STATUS,
    FIELD_POWER,
    FIELD_INSIDE,
    FIELD_OUTSIDE,
    FIELD_BATTERY_PERCENT,
)
from powerpetdoor.simulator import (
    DoorSimulator,
    DoorSimulatorState,
    DoorTimingConfig,
    Script,
    ScriptRunner,
    get_builtin_script,
    list_builtin_scripts,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Socket Access Fixture
# ============================================================================

@pytest.fixture(autouse=True)
def allow_localhost_sockets(socket_enabled):
    """Enable socket access for simulator tests.

    This is required because pytest-homeassistant-custom-component
    uses pytest-socket which blocks all socket access by default.
    The socket_enabled fixture from pytest-socket re-enables sockets.
    """
    pass  # socket_enabled is an autouse=True fixture that enables sockets


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def fast_timing() -> DoorTimingConfig:
    """Fast timing configuration for tests (sub-second operations)."""
    return DoorTimingConfig(
        rise_time=0.1,
        default_hold_time=1,
        slowing_time=0.05,
        closing_top_time=0.05,
        closing_mid_time=0.05,
        sensor_retrigger_window=0.1,
    )


@pytest.fixture
def simulator_state(fast_timing) -> DoorSimulatorState:
    """Create a simulator state with fast timing for tests."""
    return DoorSimulatorState(
        timing=fast_timing,
        hold_time=1,  # 1 second hold time for fast tests
    )


@pytest.fixture
def realtime_simulator_state() -> DoorSimulatorState:
    """Create a simulator state with default (real-time) timing for builtin scripts."""
    return DoorSimulatorState(
        hold_time=2,  # Match builtin script expectations
    )


@pytest.fixture
async def realtime_simulator(realtime_simulator_state) -> DoorSimulator:
    """Create simulator with real-time timing for builtin script tests.

    Uses default DoorTimingConfig for compatibility with builtin scripts.
    """
    sim = DoorSimulator(host="127.0.0.1", port=0, state=realtime_simulator_state)
    await sim.start()

    # Get the actual port assigned by the OS
    actual_port = sim.server.sockets[0].getsockname()[1]
    sim.port = actual_port

    yield sim

    await sim.stop()


@pytest.fixture
async def simulator(simulator_state) -> DoorSimulator:
    """Create and start a door simulator server.

    Uses a dynamic port (0) to avoid port conflicts.
    """
    sim = DoorSimulator(host="127.0.0.1", port=0, state=simulator_state)
    await sim.start()

    # Get the actual port assigned by the OS
    actual_port = sim.server.sockets[0].getsockname()[1]
    sim.port = actual_port

    yield sim

    await sim.stop()


@pytest.fixture
async def connected_client(simulator) -> PowerPetDoorClient:
    """Create a client connected to the simulator."""
    loop = asyncio.get_running_loop()

    client = PowerPetDoorClient(
        host="127.0.0.1",
        port=simulator.port,
        timeout=5.0,
        reconnect=0.5,
        keepalive=30.0,
        loop=loop,
    )

    # Connect the client
    await client.connect()

    # Wait for connection to be established
    for _ in range(50):  # 5 seconds max
        if client.available:
            break
        await asyncio.sleep(0.1)

    assert client.available, "Client failed to connect to simulator"

    yield client

    # Cleanup
    client.stop()


# ============================================================================
# Connection Tests
# ============================================================================

class TestSimulatorConnection:
    """Tests for client connection to the simulator."""

    @pytest.mark.asyncio
    async def test_client_connects_to_simulator(self, simulator):
        """Client can connect to the simulator."""
        loop = asyncio.get_running_loop()
        client = PowerPetDoorClient(
            host="127.0.0.1",
            port=simulator.port,
            timeout=5.0,
            reconnect=0.5,
            keepalive=30.0,
            loop=loop,
        )

        await client.connect()

        # Wait for connection
        for _ in range(50):
            if client.available:
                break
            await asyncio.sleep(0.1)

        assert client.available
        client.stop()

    @pytest.mark.asyncio
    async def test_multiple_clients_connect(self, simulator):
        """Multiple clients can connect to the simulator."""
        loop = asyncio.get_running_loop()
        clients = []

        try:
            for i in range(3):
                client = PowerPetDoorClient(
                    host="127.0.0.1",
                    port=simulator.port,
                    timeout=5.0,
                    reconnect=0.5,
                    keepalive=30.0,
                    loop=loop,
                )
                await client.connect()
                clients.append(client)

            # Wait for all connections
            await asyncio.sleep(0.5)

            for client in clients:
                assert client.available

            # All clients should be tracked by simulator
            assert len(simulator.protocols) == 3

        finally:
            for client in clients:
                client.stop()


# ============================================================================
# Door Status Tests
# ============================================================================

class TestDoorStatus:
    """Tests for door status queries and updates."""

    @pytest.mark.asyncio
    async def test_get_door_status_closed(self, connected_client, simulator):
        """Client can query door status when closed."""
        # Ensure door is closed
        simulator.state.door_status = DOOR_STATE_CLOSED

        # Query status - returns just the door_status string
        result = connected_client.send_message(CONFIG, CMD_GET_DOOR_STATUS, notify=True)
        door_status = await asyncio.wait_for(result, timeout=5.0)

        assert door_status == DOOR_STATE_CLOSED

    @pytest.mark.asyncio
    async def test_get_door_status_holding(self, connected_client, simulator):
        """Client can query door status when holding open."""
        simulator.state.door_status = DOOR_STATE_HOLDING

        result = connected_client.send_message(CONFIG, CMD_GET_DOOR_STATUS, notify=True)
        door_status = await asyncio.wait_for(result, timeout=5.0)

        assert door_status == DOOR_STATE_HOLDING


# ============================================================================
# Door Command Tests
# ============================================================================

class TestDoorCommands:
    """Tests for door open/close commands.

    Note: Door commands (OPEN, CLOSE, OPEN_AND_HOLD) are fire-and-forget
    in the client - they don't have response handlers and their futures
    get cancelled. We use notify=False and verify state changes instead.
    """

    @pytest.mark.asyncio
    async def test_open_command(self, connected_client, simulator):
        """OPEN command triggers door open sequence."""
        assert simulator.state.door_status == DOOR_STATE_CLOSED

        # Send open command (fire-and-forget)
        connected_client.send_message(COMMAND, CMD_OPEN, notify=False)

        # Wait for door to start opening
        await asyncio.sleep(0.3)
        assert simulator.state.door_status in (
            DOOR_STATE_RISING,
            DOOR_STATE_HOLDING,
            DOOR_STATE_SLOWING,
        )

    @pytest.mark.asyncio
    async def test_open_and_hold_command(self, connected_client, simulator):
        """OPEN_AND_HOLD command keeps door open indefinitely."""
        assert simulator.state.door_status == DOOR_STATE_CLOSED

        # Send open and hold command
        connected_client.send_message(COMMAND, CMD_OPEN_AND_HOLD, notify=False)

        # Wait for door to fully open
        await asyncio.sleep(0.3)

        assert simulator.state.door_status == DOOR_STATE_KEEPUP

    @pytest.mark.asyncio
    async def test_close_command(self, connected_client, simulator):
        """CLOSE command closes an open door."""
        # Open the door first
        simulator.state.door_status = DOOR_STATE_KEEPUP

        # Send close command
        connected_client.send_message(COMMAND, CMD_CLOSE, notify=False)

        # Wait for door to close
        await asyncio.sleep(0.5)

        assert simulator.state.door_status == DOOR_STATE_CLOSED

    @pytest.mark.asyncio
    async def test_full_open_close_cycle(self, connected_client, simulator):
        """Full door open and close cycle."""
        # Track status changes
        status_changes = []

        def track_status(status):
            status_changes.append(status)

        connected_client.add_listener(
            name="test_tracker",
            door_status_update=track_status,
        )

        # Open the door (fire-and-forget)
        connected_client.send_message(COMMAND, CMD_OPEN, notify=False)

        # Wait for full cycle (open and auto-close)
        await asyncio.sleep(2.0)

        # Should have received status updates
        assert len(status_changes) > 0

        # Door should be closed again
        assert simulator.state.door_status == DOOR_STATE_CLOSED


# ============================================================================
# Spontaneous Event Tests
# ============================================================================

class TestSpontaneousEvents:
    """Tests for spontaneous events triggered by the simulator."""

    @pytest.mark.asyncio
    async def test_sensor_trigger_inside(self, connected_client, simulator):
        """Inside sensor trigger opens the door."""
        assert simulator.state.door_status == DOOR_STATE_CLOSED
        assert simulator.state.inside is True  # Sensor enabled

        # Track status updates
        received_statuses = []

        def on_status(status):
            received_statuses.append(status)

        connected_client.add_listener(
            name="status_tracker",
            door_status_update=on_status,
        )

        # Trigger inside sensor
        simulator.trigger_sensor("inside")

        # Wait for door to start opening
        await asyncio.sleep(0.3)

        # Should have received status update
        assert len(received_statuses) > 0
        # Door should be opening or open
        assert simulator.state.door_status in (
            DOOR_STATE_RISING,
            DOOR_STATE_HOLDING,
            DOOR_STATE_SLOWING,
        )

    @pytest.mark.asyncio
    async def test_sensor_trigger_outside(self, connected_client, simulator):
        """Outside sensor trigger opens the door."""
        assert simulator.state.door_status == DOOR_STATE_CLOSED
        assert simulator.state.outside is True  # Sensor enabled

        received_statuses = []

        def on_status(status):
            received_statuses.append(status)

        connected_client.add_listener(
            name="status_tracker",
            door_status_update=on_status,
        )

        # Trigger outside sensor
        simulator.trigger_sensor("outside")

        await asyncio.sleep(0.3)

        assert len(received_statuses) > 0
        assert simulator.state.door_status in (
            DOOR_STATE_RISING,
            DOOR_STATE_HOLDING,
            DOOR_STATE_SLOWING,
        )

    @pytest.mark.asyncio
    async def test_sensor_disabled_no_trigger(self, connected_client, simulator):
        """Disabled sensor does not trigger door."""
        assert simulator.state.door_status == DOOR_STATE_CLOSED

        # Disable inside sensor
        simulator.state.inside = False

        received_statuses = []

        def on_status(status):
            received_statuses.append(status)

        connected_client.add_listener(
            name="status_tracker",
            door_status_update=on_status,
        )

        # Try to trigger inside sensor
        simulator.trigger_sensor("inside")

        await asyncio.sleep(0.3)

        # Door should still be closed
        assert simulator.state.door_status == DOOR_STATE_CLOSED
        # No status change should have occurred
        assert len(received_statuses) == 0

    @pytest.mark.asyncio
    async def test_battery_status_update(self, connected_client, simulator):
        """Battery status changes are broadcast to clients."""
        received_battery = []

        def on_battery(data):
            received_battery.append(data)

        connected_client.add_listener(
            name="battery_tracker",
            battery_update=on_battery,
        )

        # Change battery level
        simulator.set_battery(50)

        await asyncio.sleep(0.2)

        # Should have received battery update
        assert len(received_battery) > 0
        assert received_battery[-1].get(FIELD_BATTERY_PERCENT) == 50

    @pytest.mark.asyncio
    async def test_power_off_prevents_sensor_trigger(self, connected_client, simulator):
        """Power off prevents sensor triggers."""
        assert simulator.state.door_status == DOOR_STATE_CLOSED

        # Turn power off
        simulator.set_power(False)

        # Try to trigger sensor
        simulator.trigger_sensor("inside")

        await asyncio.sleep(0.3)

        # Door should still be closed
        assert simulator.state.door_status == DOOR_STATE_CLOSED


# ============================================================================
# Settings Tests
# ============================================================================

class TestSettings:
    """Tests for settings queries and updates."""

    @pytest.mark.asyncio
    async def test_get_settings(self, connected_client, simulator):
        """Client can query current settings."""
        result = connected_client.send_message(CONFIG, CMD_GET_SETTINGS, notify=True)
        settings = await asyncio.wait_for(result, timeout=5.0)

        # Settings is returned as a dict with settings fields
        assert isinstance(settings, dict)
        # Settings should include power, inside, outside states
        assert FIELD_POWER in settings
        assert FIELD_INSIDE in settings
        assert FIELD_OUTSIDE in settings

    @pytest.mark.asyncio
    async def test_enable_disable_inside_sensor(self, connected_client, simulator):
        """Client can enable/disable inside sensor."""
        # Disable inside sensor - returns sensor states dict
        result = connected_client.send_message(CONFIG, CMD_DISABLE_INSIDE, notify=True)
        sensors = await asyncio.wait_for(result, timeout=5.0)

        # Sensor commands return dict with inside/outside states
        assert isinstance(sensors, dict)
        assert simulator.state.inside is False

        # Re-enable inside sensor
        result = connected_client.send_message(CONFIG, CMD_ENABLE_INSIDE, notify=True)
        sensors = await asyncio.wait_for(result, timeout=5.0)

        assert isinstance(sensors, dict)
        assert simulator.state.inside is True

    @pytest.mark.asyncio
    async def test_power_on_off(self, connected_client, simulator):
        """Client can turn power on/off."""
        # Turn power off - returns bool value
        result = connected_client.send_message(CONFIG, CMD_POWER_OFF, notify=True)
        power_state = await asyncio.wait_for(result, timeout=5.0)

        assert power_state is False
        assert simulator.state.power is False

        # Turn power on
        result = connected_client.send_message(CONFIG, CMD_POWER_ON, notify=True)
        power_state = await asyncio.wait_for(result, timeout=5.0)

        assert power_state is True
        assert simulator.state.power is True

    @pytest.mark.asyncio
    async def test_get_battery_status(self, connected_client, simulator):
        """Client can query battery status."""
        simulator.state.battery_percent = 75

        result = connected_client.send_message(CONFIG, CMD_GET_DOOR_BATTERY, notify=True)
        battery_data = await asyncio.wait_for(result, timeout=5.0)

        # Battery data is a dict
        assert isinstance(battery_data, dict)
        assert battery_data.get(FIELD_BATTERY_PERCENT) == 75


# ============================================================================
# Obstruction and Auto-Retract Tests
# ============================================================================

class TestObstruction:
    """Tests for obstruction detection and auto-retract."""

    @pytest.mark.asyncio
    async def test_obstruction_during_close_retracts(self, connected_client, simulator):
        """Obstruction during close triggers auto-retract."""
        # Enable autoretract
        simulator.state.autoretract = True

        # Open the door first
        simulator.state.door_status = DOOR_STATE_KEEPUP

        # Start closing (fire-and-forget)
        connected_client.send_message(COMMAND, CMD_CLOSE, notify=False)

        # Wait a bit for closing to start
        await asyncio.sleep(0.1)

        # Simulate obstruction
        simulator.simulate_obstruction()

        # Wait for retract
        await asyncio.sleep(0.5)

        # Door should have retracted (opened again)
        # After retract, it will go through another close cycle
        # Just check that an auto-retract was counted
        assert simulator.state.total_auto_retracts > 0

    @pytest.mark.asyncio
    async def test_pet_in_doorway_extends_hold(self, connected_client, simulator):
        """Pet in doorway extends hold time."""
        # Open the door (fire-and-forget)
        connected_client.send_message(COMMAND, CMD_OPEN, notify=False)

        # Wait for door to be holding
        await asyncio.sleep(0.3)

        # Set pet in doorway
        simulator.set_pet_in_doorway(True)

        # Wait less than hold time
        await asyncio.sleep(0.5)

        # Door should still be holding (not closing)
        assert simulator.state.door_status in (
            DOOR_STATE_HOLDING,
            DOOR_STATE_RISING,
            DOOR_STATE_SLOWING,
        )

        # Remove pet
        simulator.set_pet_in_doorway(False)


# ============================================================================
# Script-Based Tests
# ============================================================================

class TestScriptRunner:
    """Tests using the simulator script runner."""

    @pytest.mark.asyncio
    async def test_basic_cycle_script(self, simulator):
        """Run a basic open/close cycle script."""
        script = Script.from_simple_commands([
            "set power on",
            "set inside on",
            "trigger inside",
            "wait 0.3",
            "assert door_status DOOR_HOLDING",
            "wait_for door_closed 10",
            "assert door_status DOOR_CLOSED",
        ], name="Basic Cycle")

        runner = ScriptRunner(simulator)
        success = await runner.run(script, verbose=False)

        assert success

    @pytest.mark.asyncio
    async def test_sensor_disable_script(self, simulator):
        """Script: disabled sensor should not open door."""
        script = Script.from_simple_commands([
            "set inside off",
            "trigger inside",
            "wait 0.3",
            "assert door_status DOOR_CLOSED",
        ], name="Disabled Sensor")

        runner = ScriptRunner(simulator)
        success = await runner.run(script, verbose=False)

        assert success

    @pytest.mark.asyncio
    async def test_open_and_hold_script(self, simulator):
        """Script: open with hold keeps door open."""
        script = Script.from_simple_commands([
            "open hold",
            "wait 0.3",
            "assert door_status DOOR_KEEPUP",
            "close",
            "wait_for door_closed 5",
            "assert door_status DOOR_CLOSED",
        ], name="Open and Hold")

        runner = ScriptRunner(simulator)
        success = await runner.run(script, verbose=False)

        assert success

    @pytest.mark.asyncio
    async def test_battery_notification_script(self, simulator):
        """Script: battery level changes."""
        script = Script.from_simple_commands([
            "set battery 100",
            "assert battery 100",
            "set battery 50",
            "assert battery 50",
            "set battery 15",
            "assert battery 15",
        ], name="Battery Changes")

        runner = ScriptRunner(simulator)
        success = await runner.run(script, verbose=False)

        assert success


# ============================================================================
# Builtin Script Tests
# ============================================================================

class TestBuiltinScripts:
    """Tests using all builtin scripts from pypowerpetdoor simulator.

    These tests use real-time timing and are marked as slow since builtin
    scripts are designed for interactive/demo use with realistic timing.
    Run with: pytest -m slow
    """

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_basic_cycle_builtin(self, realtime_simulator):
        """Run the builtin basic_cycle script."""
        script = get_builtin_script("basic_cycle")
        runner = ScriptRunner(realtime_simulator)
        success = await runner.run(script, verbose=False)
        assert success

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_full_test_suite_builtin(self, realtime_simulator):
        """Run the builtin full_test_suite script."""
        script = get_builtin_script("full_test_suite")
        runner = ScriptRunner(realtime_simulator)
        success = await runner.run(script, verbose=False)
        assert success

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_obstruction_test_builtin(self, realtime_simulator):
        """Run the builtin obstruction_test script."""
        script = get_builtin_script("obstruction_test")
        runner = ScriptRunner(realtime_simulator)
        success = await runner.run(script, verbose=False)
        assert success

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_pet_presence_test_builtin(self, realtime_simulator):
        """Run the builtin pet_presence_test script."""
        script = get_builtin_script("pet_presence_test")
        runner = ScriptRunner(realtime_simulator)
        success = await runner.run(script, verbose=False)
        assert success

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_power_lockout_test_builtin(self, realtime_simulator):
        """Run the builtin power_lockout_test script."""
        script = get_builtin_script("power_lockout_test")
        runner = ScriptRunner(realtime_simulator)
        success = await runner.run(script, verbose=False)
        assert success

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_safety_lock_test_builtin(self, realtime_simulator):
        """Run the builtin safety_lock_test script."""
        script = get_builtin_script("safety_lock_test")
        runner = ScriptRunner(realtime_simulator)
        success = await runner.run(script, verbose=False)
        assert success

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_schedule_test_builtin(self, realtime_simulator):
        """Run the builtin schedule_test script."""
        script = get_builtin_script("schedule_test")
        runner = ScriptRunner(realtime_simulator)
        success = await runner.run(script, verbose=False)
        assert success

    @pytest.mark.asyncio
    async def test_all_builtin_scripts_available(self):
        """Verify all expected builtin scripts are available."""
        scripts = list_builtin_scripts()
        script_names = [name for name, _ in scripts]

        expected_scripts = [
            "basic_cycle",
            "full_test_suite",
            "obstruction_test",
            "pet_presence_test",
            "power_lockout_test",
            "safety_lock_test",
            "schedule_test",
        ]

        for expected in expected_scripts:
            assert expected in script_names, f"Missing builtin script: {expected}"


# ============================================================================
# Multi-Client Notification Tests
# ============================================================================

class TestMultiClientNotifications:
    """Tests for notifications to multiple connected clients."""

    @pytest.mark.asyncio
    async def test_all_clients_receive_door_status(self, simulator):
        """All connected clients receive door status updates."""
        loop = asyncio.get_running_loop()
        clients = []
        received_updates = {0: [], 1: [], 2: []}

        try:
            # Connect 3 clients
            for i in range(3):
                client = PowerPetDoorClient(
                    host="127.0.0.1",
                    port=simulator.port,
                    timeout=5.0,
                    reconnect=0.5,
                    keepalive=30.0,
                    loop=loop,
                )
                await client.connect()

                def make_tracker(idx):
                    def tracker(status):
                        received_updates[idx].append(status)
                    return tracker

                client.add_listener(
                    name=f"tracker_{i}",
                    door_status_update=make_tracker(i),
                )
                clients.append(client)

            # Wait for all connections
            await asyncio.sleep(0.3)

            # Trigger a sensor
            simulator.trigger_sensor("inside")

            # Wait for updates
            await asyncio.sleep(0.5)

            # All clients should have received status updates
            for i in range(3):
                assert len(received_updates[i]) > 0, f"Client {i} received no updates"

        finally:
            for client in clients:
                client.stop()

    @pytest.mark.asyncio
    async def test_all_clients_receive_battery_update(self, simulator):
        """All connected clients receive battery updates."""
        loop = asyncio.get_running_loop()
        clients = []
        received_updates = {0: [], 1: []}

        try:
            # Connect 2 clients
            for i in range(2):
                client = PowerPetDoorClient(
                    host="127.0.0.1",
                    port=simulator.port,
                    timeout=5.0,
                    reconnect=0.5,
                    keepalive=30.0,
                    loop=loop,
                )
                await client.connect()

                def make_tracker(idx):
                    def tracker(data):
                        received_updates[idx].append(data)
                    return tracker

                client.add_listener(
                    name=f"tracker_{i}",
                    battery_update=make_tracker(i),
                )
                clients.append(client)

            # Wait for connections
            await asyncio.sleep(0.3)

            # Change battery
            simulator.set_battery(42)

            # Wait for updates
            await asyncio.sleep(0.3)

            # Both clients should have received battery update
            for i in range(2):
                assert len(received_updates[i]) > 0, f"Client {i} received no battery update"
                assert received_updates[i][-1].get(FIELD_BATTERY_PERCENT) == 42

        finally:
            for client in clients:
                client.stop()


# ============================================================================
# Edge Case Tests
# ============================================================================

class TestEdgeCases:
    """Tests for edge cases and error conditions."""

    @pytest.mark.asyncio
    async def test_command_while_door_moving(self, connected_client, simulator):
        """Commands while door is moving are handled correctly."""
        # Start opening the door (fire-and-forget)
        connected_client.send_message(COMMAND, CMD_OPEN, notify=False)
        await asyncio.sleep(0.1)  # Brief delay

        # Immediately send close command (fire-and-forget)
        connected_client.send_message(COMMAND, CMD_CLOSE, notify=False)

        # Wait for operations to complete
        await asyncio.sleep(1.0)

        # Door should eventually be closed
        assert simulator.state.door_status == DOOR_STATE_CLOSED

    @pytest.mark.asyncio
    async def test_rapid_sensor_triggers(self, connected_client, simulator):
        """Rapid sensor triggers are handled correctly."""
        trigger_count = 5
        initial_cycles = simulator.state.total_open_cycles

        for _ in range(trigger_count):
            simulator.trigger_sensor("inside")
            await asyncio.sleep(0.05)

        # Wait for door operations to complete
        await asyncio.sleep(3.0)

        # Should have opened at least once
        assert simulator.state.total_open_cycles > initial_cycles
        # Door should be closed
        assert simulator.state.door_status == DOOR_STATE_CLOSED

    @pytest.mark.asyncio
    async def test_client_reconnect_after_disconnect(self, simulator):
        """Client can reconnect after disconnection."""
        loop = asyncio.get_running_loop()

        client = PowerPetDoorClient(
            host="127.0.0.1",
            port=simulator.port,
            timeout=5.0,
            reconnect=False,  # Disable auto-reconnect for manual control
            keepalive=30.0,
            loop=loop,
        )

        try:
            # Connect
            await client.connect()
            await asyncio.sleep(0.3)
            assert client.available

            # Fully stop the client (stops reconnection tasks)
            client.stop()
            await asyncio.sleep(0.2)
            assert not client.available

            # Create a new client and connect
            client = PowerPetDoorClient(
                host="127.0.0.1",
                port=simulator.port,
                timeout=5.0,
                reconnect=False,
                keepalive=30.0,
                loop=loop,
            )
            await client.connect()
            await asyncio.sleep(0.3)
            assert client.available
        finally:
            client.stop()
