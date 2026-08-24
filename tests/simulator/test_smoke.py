# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""End-to-end smoke test against pypowerpetdoor's real door simulator.

No mocks. Home Assistant sets the integration up against a real TCP socket
speaking the real protocol, so this is the one layer that can catch the
integration and the library disagreeing about the wire.

Thin on purpose - the exhaustive scenarios are test-fanatic's job (see the
brief in .claude/analysis/PLAN.md). What is here is the proof that the
harness works and that a command issued in Home Assistant reaches a door.
"""

from __future__ import annotations

import asyncio

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT, CONF_TIMEOUT
from homeassistant.core import HomeAssistant
from powerpetdoor import DOOR_STATE_KEEPUP, DoorStatus
from powerpetdoor.simulator.server import DoorSimulator
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.powerpetdoor.const import (
    CONF_KEEP_ALIVE,
    CONF_RECONNECT,
    CONF_REFRESH,
    DOMAIN,
)


async def test_sets_up_against_a_real_door(
    hass: HomeAssistant, simulated_entry: MockConfigEntry
) -> None:
    """The integration completes setup talking to an actual simulator."""
    assert simulated_entry.state is ConfigEntryState.LOADED

    # State that could only have come off the wire.
    assert hass.states.get("switch.power_pet_door_connection").state == "on"
    cover = hass.states.get("cover.power_pet_door_door")
    assert cover is not None
    assert cover.state in ("open", "closed", "opening", "closing")


async def test_a_switch_change_reaches_the_simulated_door(
    hass: HomeAssistant, simulated_entry: MockConfigEntry, simulated_door: DoorSimulator
) -> None:
    """Turning a switch off changes the state the simulator holds.

    Asserted against the SIMULATOR's own state, not against a mock's call
    list: that is the difference between "we sent something" and "the door
    understood it".
    """
    assert simulated_door.state.inside is True

    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": "switch.power_pet_door_inside_sensor"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert simulated_door.state.inside is False


async def test_unload_releases_the_connection(
    hass: HomeAssistant, simulated_entry: MockConfigEntry
) -> None:
    """Unloading disconnects, so a reload does not leak a socket."""
    assert await hass.config_entries.async_unload(simulated_entry.entry_id)
    await hass.async_block_till_done()
    assert simulated_entry.state is ConfigEntryState.NOT_LOADED


async def test_open_holds_the_door_open_on_a_real_door(
    hass: HomeAssistant, simulated_entry: MockConfigEntry, simulated_door: DoorSimulator
) -> None:
    """`open` parks the door open; `cycle` is the one that closes itself.

    Asserted against the simulator's own state machine rather than a mock,
    because this is exactly the distinction that was wrong before
    pypowerpetdoor 0.4.1 - the two commands are different bytes on the wire
    and a mock would happily accept either.
    """
    coordinator = simulated_entry.runtime_data

    # Wait on the door's own status callback, not a polling loop: the door
    # pushes every transition, so there is a real event to await and no
    # reason to sleep-and-hope.
    held = asyncio.Event()

    def _watch(status: DoorStatus) -> None:
        if status is DoorStatus.KEEPUP:
            held.set()

    coordinator.door.on_status_change(_watch)

    await hass.services.async_call(
        "cover", "open_cover", {"entity_id": "cover.power_pet_door_door"}, blocking=True
    )
    async with asyncio.timeout(5):
        await held.wait()

    # KEEPUP, not HOLDING: HOLDING is the timed state that closes itself.
    assert simulated_door.state.door_status == DOOR_STATE_KEEPUP

    # ...and it STAYS there. Asserting that something does not happen does
    # require waiting: the simulator's hold_time is 1s, so a timed open
    # would have begun closing well inside this window.
    await asyncio.sleep(1.5)
    assert simulated_door.state.door_status == DOOR_STATE_KEEPUP


async def test_setup_refuses_a_listener_that_is_not_a_door(
    hass: HomeAssistant, simulated_port: int
) -> None:
    """Regression for finding B12.

    A bare TCP server that accepts the connection and then says nothing at
    all - a user's NAS, a typo'd octet that happens to land on something
    listening. `connect()` only establishes TCP and `refresh()` swallows
    every error, so on their own the flow reported success and created a
    device showing the library's constructor defaults (cover closed, power
    on, battery 100%) with `available` True. The user had no way to tell it
    from a working door.

    A real socket, not a mock: the whole point is that the transport
    succeeds and only the protocol fails, which a mock cannot demonstrate.
    """
    server = await asyncio.start_server(lambda _r, _w: None, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Not a door",
            unique_id=f"127.0.0.1:{port}",
            data={CONF_HOST: "127.0.0.1", CONF_PORT: port, CONF_NAME: "Not a door"},
            options={
                CONF_TIMEOUT: 2.0,
                CONF_RECONNECT: 1.0,
                CONF_KEEP_ALIVE: 0,
                CONF_REFRESH: 300.0,
            },
        )
        entry.add_to_hass(hass)
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Retrying, not errored: if the user really is pointing at a door
        # that is merely slow to boot, it must come back on its own.
        assert entry.state is ConfigEntryState.SETUP_RETRY
        # And no entities were published from fabricated defaults.
        assert not [s for s in hass.states.async_all() if s.entity_id.endswith("_connection")]
    finally:
        # SETUP_RETRY leaves a scheduled retry AND the library's reconnect
        # loop running against a socket that will never answer. Left alive,
        # they outlive this test and stop a LATER test's
        # `async_block_till_done()` from ever settling - which is how one
        # bad teardown hangs an entire suite rather than failing one case.
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        server.close()
        await server.wait_closed()
