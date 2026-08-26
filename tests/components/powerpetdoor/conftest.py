# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""Fixtures for the Power Pet Door tests.

`mock_door` is an in-memory double of `powerpetdoor.PowerPetDoor`. It is
fast, and it lets a test put the door in a state a real one would take a
long time to reach: flat battery, mid-travel, forty schedules.

The other way to get a door - pypowerpetdoor's real simulator on a real
socket - is in `tests/simulator/conftest.py`, because it is not something
Home Assistant core would run.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable, Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT, CONF_TIMEOUT
from homeassistant.core import HomeAssistant
from powerpetdoor import BatteryInfo, DoorStatus, NotificationSettings, PowerPetDoor
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.syrupy import HomeAssistantSnapshotExtension
from syrupy.assertion import SnapshotAssertion

from custom_components.powerpetdoor.const import (
    CONF_HOLD_MAX,
    CONF_HOLD_MIN,
    CONF_HOLD_STEP,
    CONF_KEEP_ALIVE,
    CONF_RECONNECT,
    CONF_REFRESH,
    DOMAIN,
)

TEST_HOST = "192.0.2.10"
TEST_PORT = 3000


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """A config entry for a door at TEST_HOST."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Power Pet Door",
        unique_id=f"{TEST_HOST}:{TEST_PORT}",
        data={CONF_HOST: TEST_HOST, CONF_PORT: TEST_PORT, CONF_NAME: "Power Pet Door"},
        options={
            CONF_TIMEOUT: 5.0,
            CONF_RECONNECT: 5.0,
            CONF_KEEP_ALIVE: 30.0,
            CONF_REFRESH: 300.0,
            CONF_HOLD_MIN: 2.0,
            CONF_HOLD_MAX: 8.0,
            CONF_HOLD_STEP: 2.0,
        },
    )


def _build_mock_door() -> MagicMock:
    """A `PowerPetDoor` double with a plausible, fully-populated state.

    `spec=PowerPetDoor` on purpose: it makes a typo in a property name, or a
    property the library later removes, an AttributeError in the test rather
    than a silently-passing mock. That is the failure mode that lets an
    integration keep "working" against an API that no longer exists.
    """
    door = MagicMock(spec=PowerPetDoor)

    door.host = TEST_HOST
    door.port = TEST_PORT
    door.connected = True
    # SECONDS, as `PowerPetDoor.latency` documents and `_on_ping`
    # implements (`latency_ms / 1000.0`). 0.012 is a 12 ms LAN round
    # trip. The old value of 12.0 encoded the same unit confusion the
    # sensor did, which is why `spec=PowerPetDoor` could not catch it.
    door.latency = 0.012

    door.status = DoorStatus.CLOSED
    door.is_open = False
    door.is_closed = True
    door.is_closing = False
    door.position = 0

    door.power = True
    door.inside_sensor = True
    door.outside_sensor = True
    door.auto = True
    door.safety_lock = False
    door.autoretract = True
    door.pet_proximity_keep_open = False

    door.hold_time = 4.0
    door.sensor_trigger_voltage = 1500
    door.sleep_sensor_trigger_voltage = 900
    door.timezone = "EST5EDT,M3.2.0,M11.1.0"
    door.device_time = "2026-08-23 12:00:00"

    door.battery = BatteryInfo(percent=87, present=True, ac_present=True)
    door.notifications = NotificationSettings()
    door.firmware_version = "1.7.18"
    door.hardware_version = "3 rev 1"
    door.hardware_info = {}
    door.total_open_cycles = 1234
    door.total_auto_retracts = 5
    door.has_remote_id = False
    door.has_remote_key = False
    door.schedules = []

    # Callback registration: capture the callbacks so a test can fire them
    # and assert that a push from the door reaches the entities.
    door._callbacks = {}

    def _register(name: str) -> Callable[[Callable[..., None]], None]:
        def register(callback: Callable[..., None]) -> None:
            door._callbacks.setdefault(name, []).append(callback)

        return register

    for hook in (
        "on_status_change",
        "on_settings_change",
        "on_schedule_change",
        "on_connect",
        "on_disconnect",
    ):
        setattr(door, hook, MagicMock(side_effect=_register(hook)))

    for coroutine in (
        "connect",
        "disconnect",
        "refresh",
        "refresh_settings",
        "refresh_status",
        "refresh_battery",
        "refresh_stats",
        "refresh_schedules",
        "refresh_hardware_info",
        "refresh_remote_info",
        "refresh_time",
        "open",
        "close",
        "toggle",
        "cycle",
        "set_power",
        "set_inside_sensor",
        "set_outside_sensor",
        "set_auto",
        "set_safety_lock",
        "set_autoretract",
        "set_pet_proximity_keep_open",
        "set_hold_time",
        "set_sensor_trigger_voltage",
        "set_sleep_sensor_trigger_voltage",
        "set_timezone",
        "set_notifications",
        "set_schedule",
        "delete_schedule",
        "get_schedule",
    ):
        setattr(door, coroutine, AsyncMock())

    door.refresh_schedules.return_value = []
    return door


@pytest.fixture
def mock_door() -> Generator[MagicMock]:
    """Patch the coordinator's `PowerPetDoor` with a double.

    The double takes its address FROM the constructor call rather than
    holding TEST_HOST for the life of the test. That sounds cosmetic and is
    not: every entity unique_id and the device registry identifier derive
    from `coordinator.device_identifier`, which is `door.host:door.port`. A
    double whose address never moved made those constant no matter what the
    integration actually built, so a reconfigure that renamed every entity
    in the registry was indistinguishable from one that renamed none - and
    the same blind spot hid the latency unit error.
    """
    door = _build_mock_door()

    def _construct(**kwargs: Any) -> MagicMock:
        door.host = kwargs["host"]
        door.port = kwargs["port"]
        return door

    with patch("custom_components.powerpetdoor.coordinator.PowerPetDoor", side_effect=_construct):
        yield door


@pytest.fixture
async def setup_integration(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_door: MagicMock
) -> MockConfigEntry:
    """A fully set-up config entry backed by `mock_door`."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_config_entry


SECOND_HOST = "192.0.2.20"


@pytest.fixture
def second_config_entry() -> MockConfigEntry:
    """A config entry for a SECOND door, at a different address."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Back Door",
        unique_id=f"{SECOND_HOST}:{TEST_PORT}",
        data={CONF_HOST: SECOND_HOST, CONF_PORT: TEST_PORT, CONF_NAME: "Back Door"},
        options={
            CONF_TIMEOUT: 5.0,
            CONF_RECONNECT: 5.0,
            CONF_KEEP_ALIVE: 30.0,
            CONF_REFRESH: 300.0,
            # Deliberately DIFFERENT from the first door's, so a test can
            # tell whether per-entry options leak between doors. They used
            # to: the hold-open bounds were written into a module-level
            # table, so whichever door set up last won for both.
            CONF_HOLD_MIN: 1.0,
            CONF_HOLD_MAX: 30.0,
            CONF_HOLD_STEP: 0.5,
        },
    )


@pytest.fixture
async def two_doors(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    second_config_entry: MockConfigEntry,
) -> AsyncGenerator[tuple[MockConfigEntry, MagicMock, MockConfigEntry, MagicMock]]:
    """Two independently-backed doors set up at once.

    Each entry gets its OWN door double, so a test can change one and assert
    the other did not move. Issue #9 and PR #11 were both this: two doors
    sharing state and listeners.
    """
    first_door = _build_mock_door()
    second_door = _build_mock_door()
    second_door.host = SECOND_HOST

    # Keyed by host, NOT by call order. Home Assistant sets up every entry of
    # an integration together once the component loads, so the order the
    # coordinators are constructed in is not something a test should depend
    # on - and a test that silently handed the doubles out backwards would
    # "pass" while asserting the opposite of what it reads.
    doors = {TEST_HOST: first_door, SECOND_HOST: second_door}

    with patch(
        "custom_components.powerpetdoor.coordinator.PowerPetDoor",
        side_effect=lambda **kwargs: doors[kwargs["host"]],
    ):
        mock_config_entry.add_to_hass(hass)
        second_config_entry.add_to_hass(hass)
        # Setting up the first loads the component, which loads every entry
        # it owns - so the second may already be LOADED by the time this
        # returns. Setting it up again raises OperationNotAllowed.
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        if second_config_entry.state is not ConfigEntryState.LOADED:
            assert await hass.config_entries.async_setup(second_config_entry.entry_id)
            await hass.async_block_till_done()
        yield mock_config_entry, first_door, second_config_entry, second_door


@pytest.fixture
def entity_registry_enabled_by_default() -> Generator[None]:
    """Force every entity to be registered enabled.

    Home Assistant core ships this fixture; pytest-homeassistant-custom-component
    does not re-export it, so it is defined here the same way core defines it.

    Needed by the snapshot tests: `snapshot_platform` refuses to run unless
    every entity is enabled, and this integration disables a dozen
    diagnostic and rarely-changed entities by default. Without it the
    snapshots would only ever cover what a fresh install shows, leaving the
    disabled half unpinned - which is exactly the half nobody looks at.
    Whether each entity is disabled by default is itself recorded in the
    snapshot, so nothing is lost by forcing them on here.
    """
    with patch(
        "homeassistant.helpers.entity.Entity.entity_registry_enabled_default",
        return_value=True,
    ):
        yield


@pytest.fixture
def snapshot(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    """Serialise Home Assistant objects deterministically.

    Overrides syrupy's default. A `RegistryEntry` carries `created_at`,
    `modified_at`, a generated `id` and a `device_id` - all different on
    every run - so a raw snapshot of one can never match twice. Home
    Assistant ships this extension to normalise them, and core's own tests
    apply it exactly like this.
    """
    return snapshot.use_extension(HomeAssistantSnapshotExtension)
