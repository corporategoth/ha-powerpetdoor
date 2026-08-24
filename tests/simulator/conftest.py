# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""Fixtures scoped to the simulator-backed integration tests."""

from __future__ import annotations

import asyncio
from collections.abc import Generator

import pytest
from homeassistant.core import HomeAssistant
from powerpetdoor import PowerPetDoor


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
def enable_every_entity(entity_registry_enabled_by_default: None) -> None:
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
