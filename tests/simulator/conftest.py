# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""Fixtures scoped to the simulator-backed integration tests.

These drive pypowerpetdoor's **real** simulator over a real socket. The
simulator is not written here and is not mocked: it ships in the library
(`powerpetdoor.simulator`) and speaks the actual wire protocol, so a test
using it exercises framing, timing and the library's own parsing. This is
what catches the integration and the library disagreeing, which no mock
ever can.

It lives outside `tests/components/powerpetdoor/` because Home Assistant
core would not run it - core tests do not open sockets - and that directory
is kept to exactly what core would take. The door doubles it borrows from
there are imported below.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Generator

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT, CONF_TIMEOUT
from homeassistant.core import HomeAssistant
from powerpetdoor import PowerPetDoor
from powerpetdoor.simulator.server import DoorSimulator
from powerpetdoor.simulator.state import DoorSimulatorState, DoorTimingConfig
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.powerpetdoor.const import (
    CONF_HOLD_MAX,
    CONF_HOLD_MIN,
    CONF_HOLD_STEP,
    CONF_KEEP_ALIVE,
    CONF_RECONNECT,
    CONF_REFRESH,
    DOMAIN,
)

# Re-exported so it is registered as a fixture in THIS directory too. A
# fixture is only visible to the conftest that defines it and its children,
# and the core-shaped suite is a sibling of this one, not a parent.
from tests.components.powerpetdoor.conftest import (  # noqa: F401
    entity_registry_enabled_by_default,
)


@pytest.fixture(autouse=True)
def allow_local_sockets(socket_enabled: None) -> Generator[None]:
    """Let these tests open real sockets.

    pytest-socket, which pytest-homeassistant-custom-component enables
    globally, blocks `socket.socket` outright - correctly, because a unit
    test that reaches the network is a test that fails on someone else's
    machine. These tests are the deliberate exception: their whole point is
    to speak the real protocol to a real listener.

    Scoped to this directory rather than turned off in pyproject.toml, so
    the block still protects every other test in the suite. The listener is
    pypowerpetdoor's simulator bound to an ephemeral port on loopback, so
    nothing leaves the machine.
    """
    yield


@pytest.fixture(autouse=True)
def enable_every_entity(entity_registry_enabled_by_default: None) -> None:  # noqa: F811
    """Register every entity enabled, for the whole simulator suite.

    Half this integration's surface is diagnostic and disabled by default -
    the safety lock, auto-retract, the notification toggles, the trigger
    voltages, the timezone. Those are exactly the ones no unit test has ever
    driven against a real protocol conversation, so the simulator suite
    turns them all on.

    Autouse rather than requested per test: it patches an Entity property
    and therefore has to be in place BEFORE `simulated_entry` sets the entry
    up, and an autouse fixture is guaranteed to be.
    """


@pytest.fixture
def simulator_timing() -> DoorTimingConfig:
    """Door motion fast enough for a test to wait for it honestly.

    Real timings are seconds per phase. Compressing them lets a test await
    an actual state transition instead of sleeping and hoping, which is what
    the async-determinism rule in .claude/CLAUDE.md is about.
    """
    return DoorTimingConfig(
        rise_time=0.1,
        default_hold_time=1,
        slowing_time=0.05,
        closing_top_time=0.05,
        closing_mid_time=0.05,
        sensor_retrigger_window=0.1,
    )


@pytest.fixture
async def simulated_door(
    simulator_timing: DoorTimingConfig,
) -> AsyncGenerator[DoorSimulator]:
    """Pypowerpetdoor's real door simulator, on an ephemeral port.

    Port 0 so concurrent test workers cannot collide; the caller reads the
    assigned port from `simulator.server.sockets[0].getsockname()[1]`.
    """
    simulator = DoorSimulator(
        port=0, state=DoorSimulatorState(timing=simulator_timing, hold_time=1)
    )
    await simulator.start()
    yield simulator
    await simulator.stop()


@pytest.fixture
def simulated_port(simulated_door: DoorSimulator) -> int:
    """The port the running simulator bound to."""
    port: int = simulated_door.server.sockets[0].getsockname()[1]
    return port


@pytest.fixture
async def simulated_entry(
    hass: HomeAssistant, simulated_port: int
) -> AsyncGenerator[MockConfigEntry]:
    """A config entry set up against the real simulator, no mocks involved."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Power Pet Door",
        unique_id=f"127.0.0.1:{simulated_port}",
        data={CONF_HOST: "127.0.0.1", CONF_PORT: simulated_port, CONF_NAME: "Power Pet Door"},
        options={
            CONF_TIMEOUT: 5.0,
            CONF_RECONNECT: 1.0,
            # 0 disables the keepalive; a ping every 30s would otherwise
            # leave a pending task at teardown.
            CONF_KEEP_ALIVE: 0,
            CONF_REFRESH: 300.0,
            CONF_HOLD_MIN: 2.0,
            CONF_HOLD_MAX: 8.0,
            CONF_HOLD_STEP: 2.0,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    yield entry

    # Unload BEFORE the simulator fixture stops its server. Without this the
    # simulator shuts down under a still-connected client, the library sees
    # the drop as an outage and starts its reconnect backoff, and the test
    # ends with a pending task and an ERROR line in every teardown.
    if entry.state is ConfigEntryState.LOADED:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


def watch(door: PowerPetDoor, hook: str) -> asyncio.Event:
    """An `asyncio.Event` set the next time the door pushes `hook`.

    The honest way to wait for a state change that originates at the door:
    the facade already fires a callback for every push, so there is a real
    event to await and no reason to poll or sleep. `hook` is one of
    `on_status_change`, `on_settings_change`, `on_schedule_change`,
    `on_connect`, `on_disconnect`.
    """
    event = asyncio.Event()
    getattr(door, hook)(lambda *_args: event.set())
    return event


#: How long a push may take to cross a loopback socket and be parsed before
#: the test is considered hung. Generous, because it is a deadlock backstop
#: rather than a timing assumption - a working push arrives in milliseconds.
PUSH_TIMEOUT = 10.0


async def settle(hass: HomeAssistant, event: asyncio.Event) -> None:
    """Wait for a real push to arrive, then let Home Assistant apply it.

    Two steps, because they are two different waits: the first is for bytes
    to cross the socket and be parsed, the second is for the coordinator to
    tell its entities and for their new states to be written.
    """
    async with asyncio.timeout(PUSH_TIMEOUT):
        await event.wait()
    await hass.async_block_till_done()
