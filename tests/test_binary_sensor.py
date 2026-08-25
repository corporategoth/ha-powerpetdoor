# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""Binary sensors, the schedule sensors, and the `set_schedule` action."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest
import voluptuous as vol
from homeassistant.auth.const import GROUP_ID_USER
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceNotSupported, Unauthorized
from homeassistant.util import dt as dt_util
from powerpetdoor import BatteryInfo, CommandError, Schedule, ScheduleTime
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockUser,
    async_fire_time_changed,
)

from custom_components.powerpetdoor.const import DOMAIN

#: The test harness runs Home Assistant in US/Pacific, and the door evaluates
#: its schedule in LOCAL time. Building these moments in that zone rather
#: than in UTC is deliberate: a suite written entirely in UTC would pass an
#: implementation that ignored the timezone, which is the bug that makes a
#: 06:00 window open at 23:00 for everyone west of Greenwich.
TEST_ZONE = ZoneInfo("US/Pacific")


def local(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    """A moment in Home Assistant's configured timezone."""
    return datetime(year, month, day, hour, minute, tzinfo=TEST_ZONE)


MAINS = "binary_sensor.power_pet_door_mains_power"
CHARGING = "binary_sensor.power_pet_door_battery_charging"
INSIDE_SCHEDULE = "binary_sensor.power_pet_door_inside_schedule"
OUTSIDE_SCHEDULE = "binary_sensor.power_pet_door_outside_schedule"

# [Sun, Mon, Tue, Wed, Thu, Fri, Sat]
MONDAY_ONLY = [False, True, False, False, False, False, False]
EVERY_DAY = [True] * 7


@pytest.fixture(autouse=True)
def _enable_all(entity_registry_enabled_by_default: None) -> None:
    """Three of the four plain binary sensors are disabled by default."""


def push(door: MagicMock) -> None:
    """Fire the door's settings-change callbacks, as a real push would."""
    for callback in door._callbacks["on_settings_change"]:
        callback({})


def push_schedules(door: MagicMock, schedules: list[Schedule]) -> None:
    """Put a schedule table on the door and announce it, as the door does."""
    door.schedules = schedules
    door.refresh_schedules.return_value = schedules
    for callback in door._callbacks["on_schedule_change"]:
        callback(schedules)


def sched(
    days: list[bool],
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    index: int = 0,
    inside: bool = True,
    outside: bool = False,
) -> Schedule:
    """One door schedule entry."""
    return Schedule(
        index=index,
        enabled=True,
        days_of_week=days,
        inside=inside,
        outside=outside,
        start=ScheduleTime(*start),
        end=ScheduleTime(*end),
    )


# ---------------------------------------------------------------------------
# The plain binary sensors
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("entity_id", "on_battery", "off_battery"),
    [
        (
            MAINS,
            BatteryInfo(percent=50, present=True, ac_present=True),
            BatteryInfo(percent=50, present=True, ac_present=False),
        ),
        (
            CHARGING,
            # charging = on AC and not yet full.
            BatteryInfo(percent=50, present=True, ac_present=True),
            BatteryInfo(percent=100, present=True, ac_present=True),
        ),
    ],
)
async def test_the_battery_binary_sensors_follow_the_doors_power_situation(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    entity_id: str,
    on_battery: BatteryInfo,
    off_battery: BatteryInfo,
) -> None:
    """Both states each, so a sensor wired to the wrong flag cannot pass.

    The `charging` off-case is a FULL battery on mains, not a door off
    mains: that is the pair that tells `charging` apart from `ac_present`,
    and wiring one to the other otherwise looks correct all day.
    """
    mock_door.battery = on_battery
    push(mock_door)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "on"

    mock_door.battery = off_battery
    push(mock_door)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "off"


async def test_the_mains_sensor_is_a_plug(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Device class decides the wording a voice assistant uses."""
    assert hass.states.get(MAINS).attributes["device_class"] == "plug"


# ---------------------------------------------------------------------------
# The schedule sensors
# ---------------------------------------------------------------------------


async def test_a_door_with_no_schedule_reports_its_sensors_permanently_on(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """No entries means the door never gates the sensor.

    Reporting "off" would tell the user their pet cannot get in when it can.
    """
    assert hass.states.get(INSIDE_SCHEDULE).state == "on"
    assert hass.states.get(OUTSIDE_SCHEDULE).state == "on"


async def test_each_schedule_sensor_reads_only_its_own_kind(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock, freezer: Any
) -> None:
    """One table covers both sensors, so the two must not agree by accident.

    Corrected by finding B8. The door's "no schedule means always enabled"
    default is a property of the WHOLE table - `state.py` returns True early
    only `if not self.schedules`. So once ANY entry exists, a sensor with no
    window of its own is BLOCKED, not ungated.

    Here the table holds one inside-only window, evaluated at 22:00 which it
    does not cover. Both sensors are therefore off - the inside one because
    its window has closed, the outside one because the table gates it and
    grants it nothing. Asserting the outside sensor "on" was the bug: Home
    Assistant said wide open while the door refused the pet entry.
    """
    freezer.move_to(local(2026, 8, 24, 22, 0))
    push_schedules(mock_door, [sched(MONDAY_ONLY, (6, 0), (20, 0), inside=True, outside=False)])
    await hass.async_block_till_done()

    assert hass.states.get(INSIDE_SCHEDULE).state == "off"
    assert hass.states.get(OUTSIDE_SCHEDULE).state == "off"

    # ...and the two are genuinely independent, not just equal: inside its
    # own window the inside sensor opens while the outside one stays shut.
    freezer.move_to(local(2026, 8, 24, 12, 0))
    push_schedules(mock_door, [sched(MONDAY_ONLY, (6, 0), (20, 0), inside=True, outside=False)])
    await hass.async_block_till_done()

    assert hass.states.get(INSIDE_SCHEDULE).state == "on"
    assert hass.states.get(OUTSIDE_SCHEDULE).state == "off"


async def test_a_schedule_sensor_is_on_inside_its_window(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock, freezer: Any
) -> None:
    """Midday on Monday, inside a 06:00-20:00 Monday window."""
    freezer.move_to(local(2026, 8, 24, 12, 0))
    push_schedules(mock_door, [sched(MONDAY_ONLY, (6, 0), (20, 0))])
    await hass.async_block_till_done()

    assert hass.states.get(INSIDE_SCHEDULE).state == "on"


async def test_the_schedule_engine_master_switch_overrides_every_window(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock, freezer: Any
) -> None:
    """`timersEnabled` off means the door consults no window at all.

    `is_sensor_allowed_by_schedule` checks it FIRST - before the empty-table
    default and before any window - so with the switch off the door permits
    both sensors around the clock. Reporting a closed window here made the
    `Schedule enabled` switch and this sensor contradict each other on the
    same dashboard, while the pet walked through a door the sensor said was
    shut.

    Asserted on both sides of the switch at a moment the window is CLOSED,
    because that is the only time the two readings differ.
    """
    freezer.move_to(local(2026, 8, 24, 23, 0))
    push_schedules(mock_door, [sched(MONDAY_ONLY, (6, 0), (20, 0))])
    await hass.async_block_till_done()

    assert hass.states.get(INSIDE_SCHEDULE).state == "off"

    mock_door.auto = False
    for callback in mock_door._callbacks["on_settings_change"]:
        callback({})
    await hass.async_block_till_done()

    assert hass.states.get(INSIDE_SCHEDULE).state == "on"


async def test_the_master_switch_off_leaves_no_edge_to_wake_for(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock, freezer: Any
) -> None:
    """Nothing is being enforced, so no window edge changes anything.

    Advertising the 06:00 opening would promise a transition that cannot
    happen: the sensor is already on and stays on until the user turns the
    engine back on, which arrives as a settings push and re-arms the timer.
    """
    freezer.move_to(local(2026, 8, 24, 23, 0))
    mock_door.auto = False
    push_schedules(mock_door, [sched(MONDAY_ONLY, (6, 0), (20, 0))])
    await hass.async_block_till_done()

    assert hass.states.get(INSIDE_SCHEDULE).attributes["next_event"] is None


async def test_a_schedule_sensor_turns_itself_on_when_its_window_opens(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock, freezer: Any
) -> None:
    """The sensor wakes at the edge rather than waiting for the next poll.

    Without the tracked timer a window opening at 06:00 would be reported
    whenever the next refresh happened to land - up to five minutes late on
    the default interval, which for a pet door is the difference between the
    cat getting in and not.

    Driven by moving the clock and firing the tracked timer, never by
    sleeping.
    """
    freezer.move_to(local(2026, 8, 24, 5, 59))
    push_schedules(mock_door, [sched(MONDAY_ONLY, (6, 0), (20, 0))])
    await hass.async_block_till_done()
    assert hass.states.get(INSIDE_SCHEDULE).state == "off"

    opens_at = local(2026, 8, 24, 6, 0)
    freezer.move_to(opens_at)
    async_fire_time_changed(hass, opens_at)
    await hass.async_block_till_done()

    assert hass.states.get(INSIDE_SCHEDULE).state == "on"


async def test_a_schedule_sensor_turns_itself_off_when_its_window_closes(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock, freezer: Any
) -> None:
    """The closing edge is tracked too, and re-arms from the opening one.

    Asserting only the opening edge would pass an implementation that armed
    one timer and never re-armed it - so the sensor would latch on forever.
    """
    freezer.move_to(local(2026, 8, 24, 19, 59))
    push_schedules(mock_door, [sched(MONDAY_ONLY, (6, 0), (20, 0))])
    await hass.async_block_till_done()
    assert hass.states.get(INSIDE_SCHEDULE).state == "on"

    closes_at = local(2026, 8, 24, 20, 0)
    freezer.move_to(closes_at)
    async_fire_time_changed(hass, closes_at)
    await hass.async_block_till_done()

    assert hass.states.get(INSIDE_SCHEDULE).state == "off"


async def test_a_schedule_change_re_arms_the_timer(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock, freezer: Any
) -> None:
    """Editing the schedule must not leave the sensor waiting on the old edge.

    The timer is re-armed on every coordinator update. Without that, moving
    a window from 20:00 to 09:00 would leave the sensor asleep until 20:00 -
    eleven hours reporting the wrong state, with the door doing the right
    thing all along.
    """
    freezer.move_to(local(2026, 8, 24, 8, 0))
    push_schedules(mock_door, [sched(MONDAY_ONLY, (6, 0), (20, 0))])
    await hass.async_block_till_done()
    assert hass.states.get(INSIDE_SCHEDULE).state == "on"

    # The user shortens the window to end at 09:00.
    push_schedules(mock_door, [sched(MONDAY_ONLY, (6, 0), (9, 0))])
    await hass.async_block_till_done()

    new_edge = local(2026, 8, 24, 9, 0)
    freezer.move_to(new_edge)
    async_fire_time_changed(hass, new_edge)
    await hass.async_block_till_done()

    assert hass.states.get(INSIDE_SCHEDULE).state == "off"


async def test_re_arming_cancels_the_previous_timer_rather_than_stacking(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock, freezer: Any
) -> None:
    """One timer per sensor, however many pushes arrive.

    The timer is re-armed on EVERY coordinator update, and the door is
    `local_push`: a pet walking past, a settings change, a schedule edit all
    produce one. Without cancelling the previous handle each re-arm leaks a
    live timer that fires at the old edge - twenty pushes, twenty timers, for
    the life of the entry. Measured: 3 -> 3 with the cancel, 4 -> 24 without.

    Counted through Home Assistant's own timer table rather than a private
    attribute, so it is the leak a user's instance would actually carry.
    """
    freezer.move_to(local(2026, 8, 24, 8, 0))
    push_schedules(mock_door, [sched(MONDAY_ONLY, (6, 0), (20, 0))])
    await hass.async_block_till_done()

    def _pending() -> int:
        return len(
            [
                handle
                # The real timer table, not a private attribute of ours.
                for handle in hass.loop._scheduled
                if not handle.cancelled()
            ]
        )

    baseline = _pending()
    for _ in range(20):
        push_schedules(mock_door, [sched(MONDAY_ONLY, (6, 0), (20, 0))])
        await hass.async_block_till_done()

    # A handful of unrelated timers may come and go; twenty new ones cannot.
    assert _pending() - baseline < 5


async def test_the_sensor_re_arms_after_the_edge_it_woke_for(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock, freezer: Any
) -> None:
    """Waking once is not enough - it has to wake for the NEXT edge too.

    Without re-arming inside the edge handler the sensor fires at the window
    opening, publishes `on`, and then never wakes again: it reads `on` for
    the rest of the week while the door closed the window on time. Measured.
    """
    # A two-minute window on purpose. The coordinator polls every 300s and a
    # poll also re-arms, so a long window lets the poll mask a handler that
    # never re-armed - the test would pass with the bug present.
    freezer.move_to(local(2026, 8, 24, 5, 59))
    push_schedules(mock_door, [sched(MONDAY_ONLY, (6, 0), (6, 2))])
    await hass.async_block_till_done()
    assert hass.states.get(INSIDE_SCHEDULE).state == "off"

    opening = local(2026, 8, 24, 6, 0)
    freezer.move_to(opening)
    async_fire_time_changed(hass, opening)
    await hass.async_block_till_done()
    assert hass.states.get(INSIDE_SCHEDULE).state == "on"

    # ...and the closing edge two minutes later, which only arrives if
    # waking for the first edge armed a timer for the second.
    closing = local(2026, 8, 24, 6, 2)
    freezer.move_to(closing)
    async_fire_time_changed(hass, closing)
    await hass.async_block_till_done()

    assert hass.states.get(INSIDE_SCHEDULE).state == "off"


async def test_removing_a_schedule_sensor_drops_its_timer(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    freezer: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A removed entity must not keep firing.

    Unloading the entry removes the entities while a timer is armed for
    06:00. A surviving timer would call `async_write_ha_state` on a detached
    entity - which either resurrects it with a state nothing is maintaining,
    or raises into the event loop on every edge for the life of the process.

    Both failure modes are asserted, because the state check alone would
    also pass if the timer fired and merely threw.
    """
    freezer.move_to(local(2026, 8, 24, 5, 59))
    push_schedules(mock_door, [sched(MONDAY_ONLY, (6, 0), (20, 0))])
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(setup_integration.entry_id)
    await hass.async_block_till_done()
    caplog.clear()

    edge = local(2026, 8, 24, 6, 0)
    freezer.move_to(edge)
    async_fire_time_changed(hass, edge)
    await hass.async_block_till_done()

    # Unloaded entities keep a `restored` placeholder in the state machine,
    # so the assertion is that it was NOT written back to a live value.
    assert hass.states.get(INSIDE_SCHEDULE).state == "unavailable"
    assert not [record for record in caplog.records if record.levelname in ("ERROR", "CRITICAL")]


async def test_a_schedule_that_never_changes_arms_no_timer(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock, freezer: Any
) -> None:
    """A genuinely 24/7 door - all day, every day - has no edge to wake for.

    `next_event` returns None, so nothing is scheduled. Advancing a week
    must leave the sensor on and quiet: this is the case that used to
    publish a phantom change roughly every eighth day.

    Spelled `00:00-24:00`, which is the only end that reaches the end of the
    day. A door whose entry ends at 23:59 really does close for that final
    minute, so it DOES have an edge and this test would not apply to it.
    """
    freezer.move_to(local(2026, 8, 24, 12, 0))
    push_schedules(mock_door, [sched(EVERY_DAY, (0, 0), (24, 0), inside=True, outside=True)])
    await hass.async_block_till_done()

    assert hass.states.get(INSIDE_SCHEDULE).attributes["next_event"] is None

    later = local(2026, 9, 2, 12, 0)
    freezer.move_to(later)
    async_fire_time_changed(hass, later)
    await hass.async_block_till_done()

    assert hass.states.get(INSIDE_SCHEDULE).state == "on"


async def test_the_next_event_attribute_names_the_upcoming_edge(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock, freezer: Any
) -> None:
    """Published so an automation can act ahead of a change."""
    freezer.move_to(local(2026, 8, 24, 5, 0))
    push_schedules(mock_door, [sched(MONDAY_ONLY, (6, 0), (20, 0))])
    await hass.async_block_till_done()

    upcoming = hass.states.get(INSIDE_SCHEDULE).attributes["next_event"]
    assert dt_util.parse_datetime(upcoming) == local(2026, 8, 24, 6, 0)


async def test_the_schedule_attribute_is_in_home_assistants_own_shape(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """The card consumes this, so its shape is a contract."""
    push_schedules(mock_door, [sched(MONDAY_ONLY, (6, 0), (20, 0))])
    await hass.async_block_till_done()

    attributes = hass.states.get(INSIDE_SCHEDULE).attributes
    assert attributes["schedule"] == {"monday": [{"from": "06:00", "to": "20:00"}]}
    assert attributes["schedule_count"] == 1
    assert attributes["schedule_entries"] == ["Mon: 06:00-20:00"]


async def test_the_schedule_count_totals_every_day(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """One entry covering five days counts as five windows, not one."""
    push_schedules(
        mock_door,
        [sched([False, True, True, True, True, True, False], (6, 0), (20, 0))],
    )
    await hass.async_block_till_done()

    assert hass.states.get(INSIDE_SCHEDULE).attributes["schedule_count"] == 5


async def test_the_schedule_count_totals_two_windows_on_one_day(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """The other axis, and the one every fixture missed.

    With one window per day `sum(len(slots))` and `len(schedule)` agree, so
    the count could have been counting DAYS and no test would have known. A
    user who lets the cat out morning and evening on a Monday reads 1 where
    the answer is 2 - in a template, or an automation that acts on it.
    """
    push_schedules(
        mock_door,
        [
            sched(MONDAY_ONLY, (6, 0), (9, 0), index=0),
            sched(MONDAY_ONLY, (17, 0), (20, 0), index=1),
        ],
    )
    await hass.async_block_till_done()

    attributes = hass.states.get(INSIDE_SCHEDULE).attributes
    assert attributes["schedule_count"] == 2
    assert len(attributes["schedule"]["monday"]) == 2
    assert len(attributes["schedule"]) == 1  # ...still one DAY


@pytest.mark.parametrize("entity_id", [INSIDE_SCHEDULE, OUTSIDE_SCHEDULE])
async def test_a_schedule_sensor_is_unavailable_while_the_door_is_powered_off(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    entity_id: str,
) -> None:
    """The schedule engine does nothing while the door is powered down.

    Reporting "on" there would claim the sensor is permitting entry through
    a door whose motor cannot move.
    """
    mock_door.power = False
    push(mock_door)
    await hass.async_block_till_done()

    assert hass.states.get(entity_id).state == "unavailable"


# ---------------------------------------------------------------------------
# The set_schedule action
# ---------------------------------------------------------------------------


async def test_an_automation_can_replace_a_schedule(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """PR #19: what the card can do, an automation must be able to do."""
    await hass.services.async_call(
        DOMAIN,
        "set_schedule",
        {
            "entity_id": INSIDE_SCHEDULE,
            "schedule": {"monday": [{"from": "06:00:00", "to": "20:00:00"}]},
        },
        blocking=True,
    )

    written = mock_door.set_schedule.await_args.args[0]
    assert written.inside is True
    assert written.start == ScheduleTime(6, 0)


async def test_the_action_targets_the_kind_of_the_entity_it_was_given(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """Aiming at the outside entity writes the OUTSIDE schedule.

    The entity is the only thing that selects the kind, so an action that
    ignored it would silently edit the wrong sensor's schedule.
    """
    await hass.services.async_call(
        DOMAIN,
        "set_schedule",
        {
            "entity_id": OUTSIDE_SCHEDULE,
            "schedule": {"monday": [{"from": "06:00:00", "to": "20:00:00"}]},
        },
        blocking=True,
    )

    written = mock_door.set_schedule.await_args.args[0]
    assert written.outside is True
    assert written.inside is False


async def test_the_action_refuses_a_binary_sensor_that_is_not_a_schedule(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """Regression for finding S1.

    Home Assistant matches entity services by PLATFORM, not by class, so a
    user targeting the device - or picking any of this integration's other
    binary sensors - lands in the same handler. Dispatching by name would
    then hit `getattr` on an entity with no such method and raise
    AttributeError at the user; this raises HA's own "action not supported",
    already translated by core.
    """
    with pytest.raises(ServiceNotSupported):
        await hass.services.async_call(
            DOMAIN,
            "set_schedule",
            {
                "entity_id": MAINS,
                "schedule": {"monday": [{"from": "06:00:00", "to": "20:00:00"}]},
            },
            blocking=True,
        )

    mock_door.set_schedule.assert_not_awaited()


async def test_targeting_the_whole_device_still_writes_the_schedules(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """The other side of finding S1, and the case that produced it.

    `services.yaml` can only target `domain: binary_sensor`, so a
    device-wide target sweeps all six of ours. The two schedule entities
    must still be served - rejecting the whole call because four siblings
    do not support it would make the documented device target useless.
    """
    await hass.services.async_call(
        DOMAIN,
        "set_schedule",
        {
            "entity_id": [INSIDE_SCHEDULE, OUTSIDE_SCHEDULE],
            "schedule": {"monday": [{"from": "06:00:00", "to": "20:00:00"}]},
        },
        blocking=True,
    )

    assert mock_door.set_schedule.await_count >= 2


@pytest.mark.parametrize(
    "payload",
    [
        {"funday": [{"from": "06:00", "to": "20:00"}]},
        {"monday": [{"from": "06:00"}]},
        {"monday": [{"from": "24:00", "to": "20:00"}]},
        {"monday": {"from": "06:00", "to": "20:00"}},
        {"monday": [7]},
    ],
)
async def test_the_action_refuses_a_malformed_schedule(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    payload: dict[str, Any],
) -> None:
    """Regression for finding S1, the validation half.

    The action used to take a bare `dict`, so an automation with a malformed
    payload got a raw KeyError or TypeError out of the write path while the
    card got a clean rejection for the identical input. Both entry points
    now share `SCHEDULE_PAYLOAD_SCHEMA`.
    """
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN,
            "set_schedule",
            {"entity_id": INSIDE_SCHEDULE, "schedule": payload},
            blocking=True,
        )

    mock_door.set_schedule.assert_not_awaited()


@pytest.mark.parametrize(
    "raised",
    [
        CommandError("slot table full"),
        OSError("reset"),
        TimeoutError("no answer"),
        ValueError("bad"),
    ],
)
async def test_a_schedule_the_door_refuses_is_reported_to_the_user(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock, raised: Exception
) -> None:
    """A refused write raises a translated error rather than passing silently.

    Its own key, not `command_failed`: the message names the schedule, which
    is what tells the user which of their automations to look at.
    """
    mock_door.set_schedule.side_effect = raised

    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            DOMAIN,
            "set_schedule",
            {
                "entity_id": INSIDE_SCHEDULE,
                "schedule": {"monday": [{"from": "06:00:00", "to": "20:00:00"}]},
            },
            blocking=True,
        )

    assert err.value.translation_key == "schedule_update_failed"


# ---------------------------------------------------------------------------
# The set_schedule action's admin gate - regression for finding S3
# ---------------------------------------------------------------------------

VALID_SCHEDULE = {"monday": [{"from": "06:00:00", "to": "20:00:00"}]}


async def _ordinary_user(hass: HomeAssistant) -> MockUser:
    """A normal non-admin household member.

    Deliberately the `system-users` group, NOT `system-read-only`. Home
    Assistant's default policy for this group is `{"entities": True}` - full
    entity control - so core lets these calls through and whatever refuses
    them can only be ours. A read-only user is blocked by core on every
    path, which is why a test built on one cannot tell the two apart.
    """
    group = await hass.auth.async_get_group(GROUP_ID_USER)
    return MockUser(groups=[group]).add_to_hass(hass)


async def _call_set_schedule(hass: HomeAssistant, context: Context) -> None:
    await hass.services.async_call(
        DOMAIN,
        "set_schedule",
        {"entity_id": INSIDE_SCHEDULE, "schedule": VALID_SCHEDULE},
        blocking=True,
        context=context,
    )


async def test_a_non_admin_cannot_rewrite_the_schedule(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """Regression for finding S3.

    `ws_update_schedule` is `@require_admin`, but an entity service is not,
    and Home Assistant's default policy for an ORDINARY non-admin is
    `{"entities": True}` - full entity control. So the very user the
    WebSocket refuses could call the action instead and rewrite the table.

    That is not merely inconsistent: `apply_schedule` diffs against what the
    door currently holds, so it DELETES rows an admin created. And the card
    had just told this user "You do not have permission to change this
    schedule."

    The user here is deliberately NOT `hass_read_only_user`. Home Assistant
    blocks a read-only user by itself, on both paths, so a test using one
    passes whether or not this guard exists - it cannot tell our gate from
    core's. An ordinary non-admin is the case that distinguishes them, and
    is the case that was actually exploitable.
    """
    user = await _ordinary_user(hass)

    with pytest.raises(Unauthorized):
        await _call_set_schedule(hass, Context(user_id=user.id))

    # Refused before reaching the door, not after a partial write.
    mock_door.set_schedule.assert_not_awaited()
    mock_door.delete_schedule.assert_not_awaited()


async def test_home_assistant_itself_would_have_allowed_that_user(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """The guard is load-bearing, not a restatement of core's policy.

    If Home Assistant already refused an ordinary non-admin, the test above
    would pass with the guard deleted and prove nothing. This asserts the
    premise directly: core's default policy for such a user grants entity
    control, so the refusal above can only be ours.
    """
    user = await _ordinary_user(hass)

    assert user.is_admin is False
    assert user.permissions.check_entity(INSIDE_SCHEDULE, "control") is True


async def test_an_admin_can_rewrite_the_schedule(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    hass_admin_user,
) -> None:
    """The gate must not lock out the people it is meant to admit."""
    await _call_set_schedule(hass, Context(user_id=hass_admin_user.id))
    mock_door.set_schedule.assert_awaited()


async def test_an_automation_can_rewrite_the_schedule(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """A call with no user is a script, automation or blueprint.

    Those are the action's whole reason to exist - the WebSocket API is
    browser-only, so without this path an automation could not do what the
    card can. `websocket_api.require_admin` applies the same rule.
    """
    await _call_set_schedule(hass, Context())
    mock_door.set_schedule.assert_awaited()


async def test_a_deleted_user_cannot_rewrite_the_schedule(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """A context naming a user who no longer exists is refused.

    Distinct from the no-user case: a missing user_id means "not a person",
    while a user_id that resolves to nothing means the account was removed
    between the call being made and being served. Treating that as trusted
    would be an open door.
    """
    with pytest.raises(Unauthorized):
        await _call_set_schedule(hass, Context(user_id="01JZZZZZZZZZZZZZZZZZZZZZZZ"))

    mock_door.set_schedule.assert_not_awaited()
