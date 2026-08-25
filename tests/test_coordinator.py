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
from powerpetdoor import BatteryInfo, CommandError, DoorStatus, Schedule, ScheduleTime
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


@pytest.mark.parametrize(
    "raised",
    [CommandError("busy"), OSError("connection reset"), TimeoutError("no answer")],
)
async def test_a_refresh_the_door_refuses_marks_entities_unavailable(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock, raised: Exception
) -> None:
    """A connected door that fails a refresh is still a failed refresh.

    Distinct from the disconnected case above: the socket is up, so the
    library is not reconnecting and nothing else will notice. Swallowing it
    would leave every entity showing values from before the failure with no
    sign they had gone stale.

    Driven through `refresh_status`, NOT `refresh`. The real
    `PowerPetDoor.refresh()` gathers with `return_exceptions=True` and only
    logs, so it cannot raise - a test that made a mock's `refresh` throw was
    exercising a path production can never take, and `refresh_status()`
    could be deleted from the coordinator with the whole suite green at 100%
    coverage. That deletion is the bug: a door answering TCP but not
    commands (the phone app has taken the connection - issue #18's shape)
    would keep every entity `available` on a frozen cache indefinitely.
    """
    mock_door.refresh_status.side_effect = raised

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


class TestTheDataNothingElsePolls:
    """`door.refresh()` deliberately leaves two things out, and says so.

    The clock is "a diagnostic, and it goes stale the moment it arrives";
    the remote pairing is "static pairing information, not live state".
    Both are defensible for a library and both left an entity here
    reporting a value nothing had ever set - measured on a real door, the
    Door clock sensor read `unknown` from the moment it was created, and
    the two remote binary sensors read `off`, which is a made-up answer
    rather than a missing one.
    """

    async def test_the_door_clock_is_read_on_every_refresh(
        self,
        hass: HomeAssistant,
        setup_integration: MockConfigEntry,
        mock_door: MagicMock,
    ) -> None:
        """It is live state: schedules are evaluated against this clock.

        A door whose clock or timezone has drifted opens on the wrong
        schedule with nothing else to show for it, so a value read once at
        startup and never again is barely better than none.
        """
        mock_door.refresh_time.reset_mock()

        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=DEFAULT_REFRESH_TIMEOUT + 1))
        await hass.async_block_till_done()

        assert mock_door.refresh_time.await_count >= 1

    async def test_the_remote_pairing_is_read_once_and_not_again(
        self,
        hass: HomeAssistant,
        setup_integration: MockConfigEntry,
        mock_door: MagicMock,
    ) -> None:
        """Static, so re-reading it every cycle is two round trips for nothing.

        The door is single-connection and rate-limited, which is exactly
        why the library leaves it out of the bulk refresh; asking once is
        the difference between that and an entity that never works.
        """
        assert mock_door.refresh_remote_info.await_count == 1

        for tick in (1, 2):
            async_fire_time_changed(
                hass, dt_util.utcnow() + timedelta(seconds=DEFAULT_REFRESH_TIMEOUT * tick + 1)
            )
            await hass.async_block_till_done()

        assert mock_door.refresh_remote_info.await_count == 1

    async def test_the_pairing_is_read_again_after_a_reconnect(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
        mock_door: MagicMock,
    ) -> None:
        """A door can be paired to a new remote while it is off the network.

        Asserted by setting the entry up twice, which is what a reload
        after a dropped connection does.
        """
        mock_config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        first = mock_door.refresh_remote_info.await_count

        await hass.config_entries.async_reload(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        assert mock_door.refresh_remote_info.await_count > first
