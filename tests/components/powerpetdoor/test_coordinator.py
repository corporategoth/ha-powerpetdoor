# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""The coordinator: connection lifecycle, refresh failures, diagnostics."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest
from homeassistant.const import CONF_TIMEOUT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.util import dt as dt_util
from powerpetdoor import (
    REFRESH_STEP_SETTINGS,
    BatteryInfo,
    CommandError,
    DoorStatus,
    Schedule,
    ScheduleTime,
)
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.powerpetdoor.const import (
    CONF_KEEP_ALIVE,
    CONF_RECONNECT,
    CONF_REFRESH,
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_KEEP_ALIVE_TIMEOUT,
    DEFAULT_RECONNECT_TIMEOUT,
    DEFAULT_REFRESH_TIMEOUT,
    DOMAIN,
)
from custom_components.powerpetdoor.coordinator import PowerPetDoorCoordinator

from .conftest import TEST_HOST, TEST_PORT


def dt_plus(**kwargs: Any) -> datetime:
    """A moment in the future, for `async_fire_time_changed`."""
    return dt_util.utcnow() + timedelta(**kwargs)


# Any entity will do to read availability; the power switch is enabled by
# default and present on every door.
POWER = "switch.power_pet_door_power"


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


async def test_the_door_is_built_from_the_entrys_options(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Every connection timing the user configured reaches the library.

    These are constructor arguments, which is why an options change forces a
    reload - so if they were not passed here there would be no other moment
    at which they could take effect.
    """
    mock_config_entry.add_to_hass(hass)

    with pytest.MonkeyPatch.context() as patcher:
        captured: dict[str, Any] = {}

        def _factory(**kwargs: Any) -> MagicMock:
            captured.update(kwargs)
            return MagicMock()

        patcher.setattr("custom_components.powerpetdoor.coordinator.PowerPetDoor", _factory)
        PowerPetDoorCoordinator(hass, mock_config_entry)

    assert captured["host"] == TEST_HOST
    assert captured["port"] == TEST_PORT
    assert captured["timeout"] == 5.0
    assert captured["reconnect"] == 5.0
    assert captured["keepalive"] == 30.0


async def test_an_entry_with_no_options_falls_back_to_the_declared_defaults(
    hass: HomeAssistant,
) -> None:
    """An entry created before an option existed still gets sane timings."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Old Entry",
        unique_id=f"{TEST_HOST}:{TEST_PORT}",
        data={"host": TEST_HOST, "port": TEST_PORT, "name": "Old Entry"},
        options={},
    )
    entry.add_to_hass(hass)

    with pytest.MonkeyPatch.context() as patcher:
        captured: dict[str, Any] = {}

        def _factory(**kwargs: Any) -> MagicMock:
            captured.update(kwargs)
            return MagicMock()

        patcher.setattr("custom_components.powerpetdoor.coordinator.PowerPetDoor", _factory)
        coordinator = PowerPetDoorCoordinator(hass, entry)

    assert captured["timeout"] == DEFAULT_CONNECT_TIMEOUT
    assert captured["reconnect"] == DEFAULT_RECONNECT_TIMEOUT
    assert captured["keepalive"] == DEFAULT_KEEP_ALIVE_TIMEOUT
    assert coordinator.update_interval == timedelta(seconds=DEFAULT_REFRESH_TIMEOUT)


async def test_a_zero_timeout_means_the_default_rather_than_no_wait(hass: HomeAssistant) -> None:
    """0 reads as "unset" to a user but would be an instant expiry to the door.

    `or DEFAULT` rather than `.get(key, DEFAULT)` on purpose, and this is
    the case that tells the two apart: with `.get` a stored 0 would be
    passed straight through and every command would time out immediately.
    Keepalive is the counter-example below - there 0 genuinely means "off".
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Zeroed",
        unique_id=f"{TEST_HOST}:{TEST_PORT}",
        data={"host": TEST_HOST, "port": TEST_PORT, "name": "Zeroed"},
        options={CONF_TIMEOUT: 0, CONF_KEEP_ALIVE: 0, CONF_RECONNECT: 0, CONF_REFRESH: 60},
    )
    entry.add_to_hass(hass)

    with pytest.MonkeyPatch.context() as patcher:
        captured: dict[str, Any] = {}

        def _factory(**kwargs: Any) -> MagicMock:
            captured.update(kwargs)
            return MagicMock()

        patcher.setattr("custom_components.powerpetdoor.coordinator.PowerPetDoor", _factory)
        PowerPetDoorCoordinator(hass, entry)

    assert captured["timeout"] == DEFAULT_CONNECT_TIMEOUT
    # Keepalive 0 IS meaningful - it disables the ping - so it is passed
    # through unchanged. Asserting both in one test is what pins the
    # difference between the two lookups.
    assert captured["keepalive"] == 0


async def test_the_refresh_interval_comes_from_the_entrys_options(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_door: MagicMock
) -> None:
    """The polling safety net honours the configured interval."""
    mock_config_entry.add_to_hass(hass)
    coordinator = PowerPetDoorCoordinator(hass, mock_config_entry)

    assert coordinator.update_interval == timedelta(seconds=300.0)


# ---------------------------------------------------------------------------
# Connecting
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raised",
    [CommandError("refused"), OSError("no route to host"), TimeoutError("no answer")],
)
async def test_a_door_that_will_not_answer_raises_config_entry_not_ready(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_door: MagicMock, raised: Exception
) -> None:
    """Platinum's test-before-setup, for each way a door can be unreachable.

    ConfigEntryNotReady (rather than a plain raise) is what makes Home
    Assistant retry on its own, so a door that was briefly unplugged comes
    back without the user touching anything.
    """
    mock_door.connect.side_effect = raised
    mock_config_entry.add_to_hass(hass)
    coordinator = PowerPetDoorCoordinator(hass, mock_config_entry)

    with pytest.raises(ConfigEntryNotReady) as err:
        await coordinator.async_connect()

    assert err.value.translation_key == "cannot_connect"
    assert err.value.translation_placeholders == {"host": TEST_HOST, "port": str(TEST_PORT)}


async def test_shutting_down_disconnects_the_door(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """The socket is released, or a reload leaks one per attempt."""
    await setup_integration.runtime_data.async_shutdown()

    mock_door.disconnect.assert_awaited()


# ---------------------------------------------------------------------------
# Refreshing
# ---------------------------------------------------------------------------


async def test_a_scheduled_refresh_asks_the_door_for_its_state(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """The polling safety net actually fires.

    Driven with `async_fire_time_changed`, not a sleep: the interval is 300
    seconds and no test should wait for it.
    """
    mock_door.refresh.reset_mock()

    async_fire_time_changed(hass, dt_plus(seconds=301))
    await hass.async_block_till_done()

    mock_door.refresh.assert_awaited()


async def test_a_refresh_while_disconnected_marks_entities_unavailable(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """Being disconnected is reported as unavailable, not as stale state.

    The library owns reconnection and is already trying, so the coordinator
    reports the truth rather than fighting its backoff. `refresh()` must NOT
    be attempted - queueing commands at a door that is not there is what
    fills the send queue.
    """
    mock_door.connected = False
    mock_door.refresh.reset_mock()

    async_fire_time_changed(hass, dt_plus(seconds=301))
    await hass.async_block_till_done()

    assert hass.states.get(POWER).state == "unavailable"
    mock_door.refresh.assert_not_awaited()


@pytest.mark.parametrize("lost", ["status", REFRESH_STEP_SETTINGS])
async def test_a_refresh_that_lost_a_load_bearing_step_marks_entities_unavailable(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock, lost: str
) -> None:
    """A connected door that did not answer is still a failed refresh.

    Distinct from the disconnected case above: the socket is up, so the
    library is not reconnecting and nothing else will notice. Swallowing it
    would leave every entity showing values from before the failure with no
    sign they had gone stale.

    Driven through `refresh()`'s RETURN VALUE, not an exception, because
    that is the only way this can happen. `PowerPetDoor.refresh()` gathers
    with `return_exceptions=True`, so a step the door answered with silence
    - which it does, for any command, occasionally - is reported rather
    than raised. A test that made the mock throw would exercise a path
    production cannot take.

    Both load-bearing steps, because they fail independently and each alone
    is enough: `status` is what the cover reads, `settings` is what the
    power switch reads.
    """
    mock_door.refresh.return_value = [lost]

    async_fire_time_changed(hass, dt_plus(seconds=301))
    await hass.async_block_till_done()

    assert hass.states.get(POWER).state == "unavailable"


async def test_a_refresh_that_lost_only_a_cosmetic_step_keeps_the_cache(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """The other side of that boundary, which coverage cannot see.

    The battery, the lifetime counters and the hardware version are static
    or cosmetic. Failing the whole update over one of them would blank a
    dashboard that is almost entirely correct - and on a mains-powered door
    with no battery fitted, would do it routinely.
    """
    mock_door.refresh.return_value = ["battery", "stats", "hardware_info"]

    async_fire_time_changed(hass, dt_plus(seconds=301))
    await hass.async_block_till_done()

    assert hass.states.get(POWER).state == "on"


@pytest.mark.parametrize(
    "raised",
    [CommandError("busy"), OSError("connection reset"), TimeoutError("no answer")],
)
async def test_a_refresh_that_raises_marks_entities_unavailable(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock, raised: Exception
) -> None:
    """Defence in depth: `refresh()` reports rather than raises, today.

    That is a property of the library, not of this integration, and the
    coordinator must not go quiet if it ever changes - an escaped exception
    that left entities `available` on a frozen cache is issue #18's shape.
    """
    mock_door.refresh.side_effect = raised

    async_fire_time_changed(hass, dt_plus(seconds=301))
    await hass.async_block_till_done()

    assert hass.states.get(POWER).state == "unavailable"


async def test_entities_recover_once_the_door_answers_again(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """The other side of the failure boundary.

    A test that only asserted the failure would pass with an integration
    that never recovered - which is the state issue #18's reporters were
    stuck in.
    """
    mock_door.refresh.side_effect = OSError("connection reset")
    async_fire_time_changed(hass, dt_plus(seconds=301))
    await hass.async_block_till_done()
    assert hass.states.get(POWER).state == "unavailable"

    mock_door.refresh.side_effect = None
    async_fire_time_changed(hass, dt_plus(seconds=602))
    await hass.async_block_till_done()

    assert hass.states.get(POWER).state == "on"


async def test_entities_recover_the_moment_the_door_reconnects(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """Not on the next poll - immediately, when the door says it is back.

    `available` is `door.connected AND last_update_success`, and ANY outage
    lasting longer than the refresh interval guarantees at least one failed
    poll, which sets `last_update_success` False. Telling listeners to
    re-read does not clear it, so every entity stayed `unavailable` until the
    next scheduled poll - up to a full refresh interval AFTER Home Assistant
    was demonstrably talking to the door again. Default 300 seconds; the
    options flow permits 86400.

    That is the shape of a router reboot or a power cut: the user sees the
    door reconnect and their whole dashboard stay dead for five minutes.

    Deliberately does NOT advance the clock afterwards - a test that polled
    would pass whether or not the reconnect itself fixed anything.
    """
    mock_door.connected = False
    mock_door.refresh.side_effect = OSError("connection reset")
    async_fire_time_changed(hass, dt_plus(seconds=301))
    await hass.async_block_till_done()
    assert hass.states.get(POWER).state == "unavailable"

    # The door comes back and announces it, exactly as the library does.
    mock_door.connected = True
    mock_door.refresh.side_effect = None
    for callback in mock_door._callbacks["on_connect"]:
        callback()
    await hass.async_block_till_done()

    assert hass.states.get(POWER).state == "on"


async def test_a_reconnect_whose_settings_read_was_dropped_is_not_reported_as_current(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """The door drops requests, so the reconnect refresh has to be verified.

    `PowerPetDoor.refresh()` gathers with `return_exceptions=True` and
    reports a failed step to a log, so a `GET_SETTINGS` the door answered
    with silence leaves every setting at its pre-outage value and the
    reconnect still looks successful. Marking the coordinator healthy on
    that basis pins the stale value in place AND defers the next poll a
    full interval - 300 seconds by default, 86400 if the user widened it.

    Which is not cosmetic for `power`. A door that loses mains power comes
    back with the flag reset to ON, so a user who had switched it off holds
    a cached False that is now the opposite of the truth - and every
    `PowerPetDoorPoweredEntity` keys availability off it, so the cover, the
    status sensor and the schedules go unavailable together.

    Asserted through the coordinator's own refresh, which calls
    `refresh_status()` first precisely because it is the one call that
    raises.
    """
    mock_door.connected = False
    mock_door.refresh.side_effect = OSError("connection reset")
    async_fire_time_changed(hass, dt_plus(seconds=301))
    await hass.async_block_till_done()
    assert hass.states.get(POWER).state == "unavailable"

    # The door is back, but its answer to GET_SETTINGS goes missing - the
    # silent drop, which `refresh()` reports rather than raising.
    mock_door.connected = True
    mock_door.refresh.side_effect = None
    mock_door.refresh.return_value = [REFRESH_STEP_SETTINGS]
    for callback in mock_door._callbacks["on_connect"]:
        callback()
    await hass.async_block_till_done()

    assert hass.states.get(POWER).state == "unavailable", (
        "a reconnect whose refresh did not complete was reported as current"
    )

    # ...and the retry that follows is a real read, not the deferred poll.
    # Past the request debouncer's cooldown but nowhere near the 300s
    # interval, so only the reconnect's own retry can account for this.
    mock_door.refresh.return_value = []
    for callback in mock_door._callbacks["on_connect"]:
        callback()
    async_fire_time_changed(hass, dt_plus(seconds=11))
    await hass.async_block_till_done()

    assert hass.states.get(POWER).state == "on"


# ---------------------------------------------------------------------------
# Helpers the platforms share
# ---------------------------------------------------------------------------


async def test_the_device_identifier_is_host_and_port(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Pinned by literal: changing it orphans every existing entity.

    The registry files entities under `<identifier>-<key>`, so a new spelling
    would lose the user's history and rename every entity id.
    """
    assert setup_integration.runtime_data.device_identifier == f"{TEST_HOST}:{TEST_PORT}"


async def test_the_coordinator_exposes_the_facades_schedule_cache(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """`schedules` reads through to the library rather than copying it.

    A second copy would be a second source of truth, and an entity reading
    the stale one is the class of bug the coordinator returning None exists
    to avoid.
    """
    entry = Schedule(
        index=0,
        enabled=True,
        days_of_week=[False, True, False, False, False, False, False],
        inside=True,
        outside=False,
        start=ScheduleTime(6, 0),
        end=ScheduleTime(20, 0),
    )
    mock_door.schedules = [entry]

    assert setup_integration.runtime_data.schedules == [entry]


async def test_diagnostics_report_the_whole_door(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """Everything a bug report needs, in one download.

    Asserted field by field because this is what a maintainer reads when a
    user cannot reproduce a problem - a missing key here is a round trip
    asking for it.
    """
    mock_door.status = DoorStatus.HOLDING
    mock_door.position = 100
    mock_door.battery = BatteryInfo(percent=64, present=True, ac_present=False)

    report = setup_integration.runtime_data.diagnostics()

    assert report["connected"] is True
    # 0.012 s from the door becomes 12 ms in a key that says so.
    assert report["latency_ms"] == 12.0
    assert report["status"] == "DOOR_HOLDING"
    assert report["position"] == 100
    assert report["firmware_version"] == "1.7.18"
    assert report["hardware_version"] == "3 rev 1"
    assert report["timezone"] == "EST5EDT,M3.2.0,M11.1.0"
    assert report["settings"]["hold_time"] == 4.0
    assert report["settings"]["sensor_trigger_voltage"] == 1500
    assert report["battery"] == {
        "percent": 64,
        "present": True,
        "ac_present": False,
        # Derived by the library, and both are reported: a door on battery
        # is discharging and not charging, and a report showing neither is
        # how a mis-derived pair looks.
        "charging": False,
        "discharging": True,
    }
    assert report["stats"]["total_open_cycles"] == 1234
    assert report["remote"] == {"has_remote_id": False, "has_remote_key": False}
    assert report["schedules"] == []


async def test_diagnostics_serialise_the_schedule_table(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """Schedules go in as dicts, or the download is not JSON-serialisable.

    A dataclass in a diagnostics payload raises inside Home Assistant's own
    download handler, which the user sees as a failed download with no
    explanation.
    """
    mock_door.schedules = [
        Schedule(
            index=3,
            enabled=True,
            days_of_week=[False, True, False, False, False, False, False],
            inside=True,
            outside=False,
            start=ScheduleTime(6, 0),
            end=ScheduleTime(20, 0),
        )
    ]

    report = setup_integration.runtime_data.diagnostics()

    assert len(report["schedules"]) == 1
    assert isinstance(report["schedules"][0], dict)
    assert report["schedules"][0]["index"] == 3
