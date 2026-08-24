# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""The door acts; Home Assistant follows.

The mirror of test_outbound.py, and the half no mock can stand in for. Here
the SIMULATOR is driven the way a real door behaves on its own - a pet trips
a sensor, the battery drains, mains is pulled, someone edits the schedule
from the phone app - and the assertion is that the Home Assistant entity
ends up telling the user the truth.

Two mechanisms deliver a change, and they are not interchangeable:

* **Push.** Door status, the full settings block, schedules and
  connectivity fire a callback on the library's facade, which the
  coordinator turns into `async_update_listeners()`. These arrive at once.
* **Poll.** Battery, mains, the lifetime counters and the hold time are
  applied to the facade's cache but fire no callback, so an entity only
  re-reads them on the coordinator's scheduled refresh. Those tests drive
  that refresh explicitly with `async_fire_time_changed` rather than
  pretending a push arrives.

Which of the two a given value uses is asserted where it matters, because
it is the difference between a low-battery automation firing now and firing
up to a refresh interval late.
"""

from __future__ import annotations

import asyncio

import pytest
from homeassistant.core import HomeAssistant
from powerpetdoor import DOOR_STATE_CLOSED, DOOR_STATE_KEEPUP, DoorStatus
from powerpetdoor.simulator.server import DoorSimulator
from powerpetdoor.simulator.state import Schedule as SimSchedule
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import PUSH_TIMEOUT, settle, watch

COVER = "cover.power_pet_door_door"
STATUS = "sensor.power_pet_door_door_status"
BATTERY = "sensor.power_pet_door_battery"
MAINS = "binary_sensor.power_pet_door_mains_power"
CHARGING = "binary_sensor.power_pet_door_battery_charging"
INSIDE_SCHEDULE = "binary_sensor.power_pet_door_inside_schedule"
OUTSIDE_SCHEDULE = "binary_sensor.power_pet_door_outside_schedule"


async def poll(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Run the coordinator's refresh and wait for it, now.

    The safety net for everything the door applies to the library's cache
    without announcing it in a way the entities can act on. Awaited rather
    than fired through the clock: the refresh does real socket I/O, so
    `async_fire_time_changed` starts it but `async_block_till_done` can
    return before the door has answered - which would make these tests
    flaky rather than deterministic.
    """
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


async def reach(door: object, status: DoorStatus) -> None:
    """Wait until the FACADE has seen the door reach `status`.

    Deliberately not `simulated_door.wait_for_status`: that is the far side
    of the socket. What these tests need to know is that the change crossed
    the wire and was parsed, which is the moment the entity can follow.
    """
    reached = asyncio.Event()

    def _watch(new: DoorStatus) -> None:
        if new is status:
            reached.set()

    door.on_status_change(_watch)
    if door.status is status:
        reached.set()
    async with asyncio.timeout(PUSH_TIMEOUT):
        await reached.wait()


# ---------------------------------------------------------------------------
# The motor, moving on its own
# ---------------------------------------------------------------------------


async def test_a_door_opened_at_the_door_itself_is_reported_in_home_assistant(
    hass: HomeAssistant, simulated_entry: MockConfigEntry, simulated_door: DoorSimulator
) -> None:
    """Someone presses the button on the door; the cover follows.

    Nothing in Home Assistant asked for this - it is the door reporting a
    change it made itself, which is the whole claim behind `local_push`.
    """
    coordinator = simulated_entry.runtime_data
    assert hass.states.get(COVER).state == "closed"

    await simulated_door.open_door(hold=True)
    await reach(coordinator.door, DoorStatus.KEEPUP)
    await hass.async_block_till_done()

    assert hass.states.get(COVER).state == "open"
    assert hass.states.get(STATUS).state == "keepup"


async def test_a_door_closing_on_its_own_is_reported_in_home_assistant(
    hass: HomeAssistant, simulated_entry: MockConfigEntry, simulated_door: DoorSimulator
) -> None:
    """...and back down again."""
    coordinator = simulated_entry.runtime_data
    await simulated_door.open_door(hold=True)
    await reach(coordinator.door, DoorStatus.KEEPUP)
    await hass.async_block_till_done()

    await simulated_door.close_door()
    await reach(coordinator.door, DoorStatus.CLOSED)
    await hass.async_block_till_done()

    assert hass.states.get(COVER).state == "closed"
    assert hass.states.get(STATUS).state == "closed"


async def test_a_pet_tripping_a_sensor_opens_the_door_and_home_assistant_says_so(
    hass: HomeAssistant, simulated_entry: MockConfigEntry, simulated_door: DoorSimulator
) -> None:
    """The commonest real event there is, and one only the simulator can stage.

    A pet walks up, the inside sensor triggers, the door opens itself. No
    command was issued from Home Assistant at all - so this is the path a
    presence automation actually watches, and a mock cannot produce it.
    """
    coordinator = simulated_entry.runtime_data
    assert hass.states.get(COVER).state == "closed"

    simulated_door.trigger_sensor("inside")
    await reach(coordinator.door, DoorStatus.HOLDING)
    await hass.async_block_till_done()

    assert hass.states.get(COVER).state == "open"


async def test_the_cover_reports_the_flap_position_the_door_reports(
    hass: HomeAssistant, simulated_entry: MockConfigEntry, simulated_door: DoorSimulator
) -> None:
    """Position tracks the real state machine, not a guess.

    Asserted at rest rather than mid-travel: the intermediate states are
    genuinely transient, and a test that raced them would be the
    sleep-and-hope this suite exists to avoid.
    """
    coordinator = simulated_entry.runtime_data

    await simulated_door.open_door(hold=True)
    await reach(coordinator.door, DoorStatus.KEEPUP)
    await hass.async_block_till_done()
    assert hass.states.get(COVER).attributes["current_position"] == 100

    await simulated_door.close_door()
    await reach(coordinator.door, DoorStatus.CLOSED)
    await hass.async_block_till_done()
    assert hass.states.get(COVER).attributes["current_position"] == 0


async def test_a_completed_cycle_increments_the_lifetime_counter_on_the_door(
    hass: HomeAssistant, simulated_entry: MockConfigEntry, simulated_door: DoorSimulator
) -> None:
    """The door counts its own openings; the sensor reports that count.

    The counter lives on the door and is only re-read on refresh, so the
    poll is explicit. Asserting it moved AT ALL is the point - a sensor
    wired to the wrong statistic reads a plausible number forever.
    """
    coordinator = simulated_entry.runtime_data
    await poll(hass, simulated_entry)
    before = int(hass.states.get("sensor.power_pet_door_total_open_cycles").state)

    await simulated_door.open_door(hold=True)
    await reach(coordinator.door, DoorStatus.KEEPUP)
    await simulated_door.close_door()
    await reach(coordinator.door, DoorStatus.CLOSED)
    await hass.async_block_till_done()

    await poll(hass, simulated_entry)

    after = int(hass.states.get("sensor.power_pet_door_total_open_cycles").state)
    assert after == before + 1
    assert simulated_door.state.total_open_cycles == after


# ---------------------------------------------------------------------------
# Settings changed on the door - these DO push
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("entity_id", "field", "inverted"),
    [
        ("switch.power_pet_door_inside_sensor", "inside", False),
        ("switch.power_pet_door_outside_sensor", "outside", False),
        ("switch.power_pet_door_schedule_enabled", "auto", False),
        ("switch.power_pet_door_outside_safety_lock", "safety_lock", False),
        ("switch.power_pet_door_auto_retract", "autoretract", False),
        ("switch.power_pet_door_pet_proximity_keep_open", "cmd_lockout", True),
    ],
)
async def test_a_setting_changed_on_the_door_reaches_the_switch(
    hass: HomeAssistant,
    simulated_entry: MockConfigEntry,
    simulated_door: DoorSimulator,
    entity_id: str,
    field: str,
    inverted: bool,
) -> None:
    """Someone changes a setting from the phone app; the switch follows.

    The door accepts one client at a time, so in practice this is what a
    user sees after disconnecting Home Assistant, changing something in the
    manufacturer's app and reconnecting - and `cmd_lockout` is here again
    because the read path must un-invert exactly as the write path inverts.
    """
    coordinator = simulated_entry.runtime_data

    setattr(simulated_door.state, field, True)
    event = watch(coordinator.door, "on_settings_change")
    simulated_door.broadcast_settings()
    await settle(hass, event)

    assert hass.states.get(entity_id).state == ("off" if inverted else "on")

    setattr(simulated_door.state, field, False)
    event = watch(coordinator.door, "on_settings_change")
    simulated_door.broadcast_settings()
    await settle(hass, event)

    assert hass.states.get(entity_id).state == ("on" if inverted else "off")


async def test_powering_the_real_door_off_makes_the_motor_entities_unavailable(
    hass: HomeAssistant, simulated_entry: MockConfigEntry, simulated_door: DoorSimulator
) -> None:
    """The door powered down at the door itself.

    The cover and the buttons become unavailable because the motor genuinely
    cannot move; the power switch and the connection switch must NOT, or
    there is no way back.
    """
    coordinator = simulated_entry.runtime_data

    simulated_door.state.power = False
    event = watch(coordinator.door, "on_settings_change")
    simulated_door.broadcast_settings()
    await settle(hass, event)

    assert hass.states.get(COVER).state == "unavailable"
    assert hass.states.get("button.power_pet_door_open").state == "unavailable"
    assert hass.states.get("switch.power_pet_door_power").state == "off"
    assert hass.states.get("switch.power_pet_door_connection").state == "on"


async def test_powering_the_real_door_back_on_restores_the_motor_entities(
    hass: HomeAssistant, simulated_entry: MockConfigEntry, simulated_door: DoorSimulator
) -> None:
    """The other side of the gate, driven over the wire.

    Without this, an integration that never recovered from a power-off would
    satisfy the test above.
    """
    coordinator = simulated_entry.runtime_data

    simulated_door.state.power = False
    event = watch(coordinator.door, "on_settings_change")
    simulated_door.broadcast_settings()
    await settle(hass, event)
    assert hass.states.get(COVER).state == "unavailable"

    simulated_door.state.power = True
    event = watch(coordinator.door, "on_settings_change")
    simulated_door.broadcast_settings()
    await settle(hass, event)

    # The concrete state. "Not unavailable" also accepted "unknown", which is
    # exactly as broken to a user - round 3 tightened seven of these eight
    # sites and this one was missed.
    assert hass.states.get(COVER).state == "closed"
    assert hass.states.get("switch.power_pet_door_power").state == "on"


async def test_a_hold_time_changed_on_the_door_reaches_the_number(
    hass: HomeAssistant, simulated_entry: MockConfigEntry, simulated_door: DoorSimulator
) -> None:
    """Seconds out of the door, seconds on the dashboard.

    The wire carries centiseconds, so this is the read half of the scaling
    asserted in the outbound suite - a door holding for 6s must not read as
    600 on the slider.

    Driven through the refresh rather than the settings push: the library
    fires `on_settings_change` before it has applied the hold time, the
    timezone and the trigger voltages from that same message, so an entity
    that re-reads on the callback sees the PREVIOUS value. Asserting the
    push here would be asserting that bug.
    """
    simulated_door.state.hold_time = 6.0
    await poll(hass, simulated_entry)

    assert float(hass.states.get("number.power_pet_door_hold_open_time").state) == 6.0


async def test_a_trigger_voltage_changed_on_the_door_reaches_the_number(
    hass: HomeAssistant, simulated_entry: MockConfigEntry, simulated_door: DoorSimulator
) -> None:
    """Millivolts out of the door, volts on the dashboard."""
    simulated_door.state.sensor_trigger_voltage = 2500
    await poll(hass, simulated_entry)

    assert float(hass.states.get("number.power_pet_door_sensor_trigger_voltage").state) == 2.5


async def test_a_timezone_changed_on_the_door_reaches_the_select(
    hass: HomeAssistant, simulated_entry: MockConfigEntry, simulated_door: DoorSimulator
) -> None:
    """The raw POSIX rule is always exposed, whatever name is shown.

    Many IANA zones share one rule, so the attribute is the only place the
    door's literal value is visible - and it is what a bug report needs.
    """
    simulated_door.state.timezone = "Europe/London"
    await poll(hass, simulated_entry)

    state = hass.states.get("select.power_pet_door_timezone")
    assert state.attributes["posix_tz"] == simulated_door.state.wire_timezone()


# ---------------------------------------------------------------------------
# Battery and mains - these do NOT push; see the module docstring
# ---------------------------------------------------------------------------


async def test_a_draining_battery_is_reported_after_a_refresh(
    hass: HomeAssistant, simulated_entry: MockConfigEntry, simulated_door: DoorSimulator
) -> None:
    """The door's battery level reaches the sensor.

    Driven through the coordinator's refresh rather than a push, because
    the library applies a battery message to its cache without firing a
    callback - so nothing tells the entity to re-read until the next poll.
    """
    simulated_door.set_battery(42)
    await poll(hass, simulated_entry)

    assert hass.states.get(BATTERY).state == "42"


async def test_a_flat_battery_is_reported_as_zero_rather_than_unknown(
    hass: HomeAssistant, simulated_entry: MockConfigEntry, simulated_door: DoorSimulator
) -> None:
    """A fitted battery at 0% is a real, alarming reading.

    The boundary that decides it is `present`, not the number - so a door
    with a genuinely flat battery must publish 0 and set off every alert it
    should, rather than going quiet.
    """
    simulated_door.set_battery(0)
    await poll(hass, simulated_entry)

    assert hass.states.get(BATTERY).state == "0"


async def test_a_door_with_no_battery_fitted_reports_no_reading(
    hass: HomeAssistant, simulated_entry: MockConfigEntry, simulated_door: DoorSimulator
) -> None:
    """The other side of that boundary, off a real door.

    A mains-only door reports 0% with `present` false. Publishing that 0
    would show a dead battery on every dashboard and fire every low-battery
    automation, forever, for a door that has no battery at all.
    """
    simulated_door.set_battery_present(False)
    await poll(hass, simulated_entry)

    assert hass.states.get(BATTERY).state == "unknown"


async def test_pulling_the_mains_lead_is_reported_by_the_plug_sensor(
    hass: HomeAssistant, simulated_entry: MockConfigEntry, simulated_door: DoorSimulator
) -> None:
    """The event a "power cut" automation is built on."""
    assert hass.states.get(MAINS).state == "on"

    simulated_door.set_ac_present(False)
    await poll(hass, simulated_entry)

    assert hass.states.get(MAINS).state == "off"


async def test_plugging_the_mains_lead_back_in_is_reported_too(
    hass: HomeAssistant, simulated_entry: MockConfigEntry, simulated_door: DoorSimulator
) -> None:
    """...and the recovery, which is what clears the alert."""
    simulated_door.set_ac_present(False)
    await poll(hass, simulated_entry)
    assert hass.states.get(MAINS).state == "off"

    simulated_door.set_ac_present(True)
    await poll(hass, simulated_entry)

    assert hass.states.get(MAINS).state == "on"


async def test_a_charging_battery_is_distinguished_from_a_full_one(
    hass: HomeAssistant, simulated_entry: MockConfigEntry, simulated_door: DoorSimulator
) -> None:
    """Charging means on mains AND not yet full.

    The pair that separates `charging` from `mains_power`: both are on
    mains, and only the part-charged one is charging. A sensor wired to
    `ac_present` passes every other test in this file.
    """
    simulated_door.set_ac_present(True)
    simulated_door.set_battery(50)
    await poll(hass, simulated_entry)
    assert hass.states.get(CHARGING).state == "on"
    assert hass.states.get(MAINS).state == "on"

    simulated_door.set_battery(100)
    await poll(hass, simulated_entry)
    assert hass.states.get(CHARGING).state == "off"
    assert hass.states.get(MAINS).state == "on"


# ---------------------------------------------------------------------------
# Schedules changed on the door
# ---------------------------------------------------------------------------


async def test_a_schedule_added_on_the_door_reaches_the_schedule_sensor(
    hass: HomeAssistant, simulated_entry: MockConfigEntry, simulated_door: DoorSimulator
) -> None:
    """Someone edits the schedule from the phone app; the card must follow.

    The attributes are what the Lovelace card renders, so this is the read
    half of the contract that the WebSocket tests exercise from the other
    end - and it is asserted off a real slot table rather than a fixture.
    """
    coordinator = simulated_entry.runtime_data

    event = watch(coordinator.door, "on_schedule_change")
    simulated_door.add_schedule(
        SimSchedule(
            index=0,
            enabled=True,
            # [Sun..Sat]: Monday only.
            days_of_week=[False, True, False, False, False, False, False],
            inside=True,
            outside=False,
            start_hour=6,
            start_min=0,
            end_hour=20,
            end_min=0,
        )
    )
    await settle(hass, event)

    attributes = hass.states.get(INSIDE_SCHEDULE).attributes
    assert attributes["schedule"] == {"monday": [{"from": "06:00", "to": "20:00"}]}
    assert attributes["schedule_entries"] == ["Mon: 06:00-20:00"]


async def test_a_schedule_for_one_sensor_does_not_appear_on_the_other(
    hass: HomeAssistant, simulated_entry: MockConfigEntry, simulated_door: DoorSimulator
) -> None:
    """One table, two sensors, read apart - proven on a real door.

    The door stores both kinds in one slot table, so the split happens
    entirely on our side and is exactly the kind of thing that reads
    correctly against a hand-built fixture and wrongly against real wire
    data, where the flags arrive as ints rather than bools.
    """
    coordinator = simulated_entry.runtime_data

    event = watch(coordinator.door, "on_schedule_change")
    simulated_door.add_schedule(
        SimSchedule(
            index=0,
            enabled=True,
            days_of_week=[False, True, False, False, False, False, False],
            inside=True,
            outside=False,
            start_hour=6,
            end_hour=20,
        )
    )
    await settle(hass, event)

    assert hass.states.get(INSIDE_SCHEDULE).attributes["schedule_count"] == 1
    assert hass.states.get(OUTSIDE_SCHEDULE).attributes["schedule"] == {}


async def test_a_schedule_deleted_on_the_door_clears_the_schedule_sensor(
    hass: HomeAssistant, simulated_entry: MockConfigEntry, simulated_door: DoorSimulator
) -> None:
    """A window removed at the door disappears from Home Assistant.

    The sensor goes back to "on" because a door with no schedule leaves its
    sensors permanently enabled - reporting "off" would tell the user their
    pet cannot get in when it can.
    """
    coordinator = simulated_entry.runtime_data

    event = watch(coordinator.door, "on_schedule_change")
    simulated_door.add_schedule(
        SimSchedule(
            index=0,
            enabled=True,
            days_of_week=[False, True, False, False, False, False, False],
            inside=True,
            outside=False,
            start_hour=6,
            end_hour=20,
        )
    )
    await settle(hass, event)
    assert hass.states.get(INSIDE_SCHEDULE).attributes["schedule_count"] == 1

    event = watch(coordinator.door, "on_schedule_change")
    simulated_door.remove_schedule(0)
    await settle(hass, event)

    assert hass.states.get(INSIDE_SCHEDULE).attributes["schedule"] == {}
    assert hass.states.get(INSIDE_SCHEDULE).state == "on"


async def test_a_factory_schedule_read_off_a_real_door_is_reported_verbatim(
    hass: HomeAssistant, simulated_entry: MockConfigEntry, simulated_door: DoorSimulator
) -> None:
    """A factory schedule crosses the wire unchanged.

    A factory door ships 00:00-23:59 on all seven days for both sensors.
    Measured against firmware 1.7.18, 23:59 is NOT a special end-of-day - the
    engine is `start <= now < end` and the device accepts and preserves
    24:00, so there is nothing to round up to and nothing to guess at. The
    entry is therefore reported exactly as it arrived, which is what keeps an
    edit to one day from rewriting all seven.

    The round trip through the wire is what makes this different from the
    unit test: the flags arrive as ints and the times as nested objects.
    """
    coordinator = simulated_entry.runtime_data

    event = watch(coordinator.door, "on_schedule_change")
    simulated_door.add_schedule(
        SimSchedule(
            index=0,
            enabled=True,
            days_of_week=[True] * 7,
            inside=True,
            outside=True,
            start_hour=0,
            start_min=0,
            end_hour=23,
            end_min=59,
        )
    )
    await settle(hass, event)

    for entity_id in (INSIDE_SCHEDULE, OUTSIDE_SCHEDULE):
        attributes = hass.states.get(entity_id).attributes
        # Spelled back exactly as it arrived - 23:59, not rounded up to the
        # end of the day and not rewritten to midnight. A door holding this
        # entry must not be edited by the act of reading it.
        assert attributes["schedule"]["monday"] == [{"from": "00:00", "to": "23:59"}]
        assert hass.states.get(entity_id).state == "on"

    # ...and 23:59 really is one minute short of the day, so unlike a
    # 00:00-24:00 door this one DOES have an edge to wake for.
    assert hass.states.get(INSIDE_SCHEDULE).attributes["next_event"] is not None


# ---------------------------------------------------------------------------
# Connectivity
# ---------------------------------------------------------------------------


async def test_the_integration_reads_real_state_off_the_door_at_setup(
    hass: HomeAssistant, simulated_entry: MockConfigEntry, simulated_door: DoorSimulator
) -> None:
    """Everything below came off the wire during setup, not from a default.

    The values are asserted against the SIMULATOR's own state rather than
    against constants, so a door configured differently would still have to
    agree - which is what makes this a round-trip test and not a restatement
    of the fixture.
    """
    assert hass.states.get("switch.power_pet_door_connection").state == "on"
    assert hass.states.get("switch.power_pet_door_power").state == (
        "on" if simulated_door.state.power else "off"
    )
    assert hass.states.get("switch.power_pet_door_inside_sensor").state == (
        "on" if simulated_door.state.inside else "off"
    )
    assert float(hass.states.get("number.power_pet_door_hold_open_time").state) == (
        simulated_door.state.hold_time
    )
    assert hass.states.get(STATUS).state == DOOR_STATE_CLOSED.removeprefix("DOOR_").lower()


async def test_the_door_reports_itself_open_over_a_real_connection(
    hass: HomeAssistant, simulated_entry: MockConfigEntry, simulated_door: DoorSimulator
) -> None:
    """A last end-to-end pass: open the door, read every affected entity.

    The cover, the raw status sensor and the simulator must agree. They read
    the same fact through three different paths, and a disagreement between
    them is precisely what a single-entity assertion cannot see.
    """
    coordinator = simulated_entry.runtime_data

    await simulated_door.open_door(hold=True)
    await reach(coordinator.door, DoorStatus.KEEPUP)
    await hass.async_block_till_done()

    assert simulated_door.state.door_status == DOOR_STATE_KEEPUP
    assert hass.states.get(STATUS).state == "keepup"
    assert hass.states.get(COVER).state == "open"
    assert hass.states.get(COVER).attributes["current_position"] == 100


async def test_a_real_close_reports_every_state_including_the_first(
    hass: HomeAssistant, simulated_entry: MockConfigEntry, simulated_door: DoorSimulator
) -> None:
    """The closing sequence a real door sends, across the wire, end to end.

    Measured on firmware 1.7.18: closing has THREE states, and DOOR_CLOSING -
    the motor starting before the flap moves - comes first. The library did
    not know it, so every close briefly produced DoorStatus.UNKNOWN: the
    status sensor read `unknown`, the cover was neither open nor closed, and
    a warning was logged. Once per close, on every door.

    Asserted here rather than only in the library because the whole path has
    to carry it - the wire, the enum, the sensor's declared options and its
    translations. A state the sensor has not declared is dropped from
    long-term statistics, so an undeclared state is a silent gap in history.
    """
    coordinator = simulated_entry.runtime_data
    seen: list[str] = []

    def _watch(status: DoorStatus) -> None:
        seen.append(status.name)

    coordinator.door.on_status_change(_watch)

    await simulated_door.open_door(hold=True)
    await reach(coordinator.door, DoorStatus.KEEPUP)
    await hass.async_block_till_done()

    await simulated_door.close_door()
    await reach(coordinator.door, DoorStatus.CLOSED)
    await hass.async_block_till_done()

    assert "UNKNOWN" not in seen, "a status the library cannot name reached Home Assistant"
    closing_run = seen[seen.index("KEEPUP") + 1 :]
    assert closing_run[:3] == ["CLOSING", "CLOSING_TOP_OPEN", "CLOSING_MID_OPEN"]

    # ...and the state the user actually sees is a declared, translated one.
    assert "closing" in hass.states.get(STATUS).attributes["options"]
