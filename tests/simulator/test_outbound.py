# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""Every control, driven from Home Assistant, asserted on the real door.

No mocks. Each test performs the action a user performs and then reads
`simulated_door.state` - the simulator's OWN state, on the far side of a
real socket and the real wire protocol.

That distinction is the point of this file. A mock assertion says "we sent
something"; this says "the door understood it". The two differ whenever the
integration and the library disagree about a command's shape, its polarity,
or its units - and every one of those has happened here at least once.
"""

from __future__ import annotations

import asyncio

import pytest
from homeassistant.core import HomeAssistant
from powerpetdoor import (
    DOOR_STATE_CLOSED,
    DOOR_STATE_HOLDING,
    DOOR_STATE_KEEPUP,
    DOOR_STATE_RISING,
)
from powerpetdoor.simulator.server import DoorSimulator
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.powerpetdoor.const import DOMAIN
from custom_components.powerpetdoor.schedule import apply_schedule
from custom_components.powerpetdoor.tz_utils import get_posix_tz_string

# ---------------------------------------------------------------------------
# Switches
# ---------------------------------------------------------------------------

#: entity_id, the simulator state field it drives, and whether the switch
#: reads the same way round as the field.
#:
#: `pet_proximity_keep_open` is the inverted one: the wire calls it "cmd
#: lockout" and the library already presents it the way a user thinks about
#: it, so turning the SWITCH on must clear the FIELD. Previous versions
#: carried their own `inverted` flag and re-inverted what the library had
#: already inverted, which is precisely the class of bug a mock cannot see.
SWITCH_FIELDS = [
    ("switch.power_pet_door_power", "power", False),
    ("switch.power_pet_door_inside_sensor", "inside", False),
    ("switch.power_pet_door_outside_sensor", "outside", False),
    ("switch.power_pet_door_schedule_enabled", "auto", False),
    ("switch.power_pet_door_outside_safety_lock", "safety_lock", False),
    ("switch.power_pet_door_auto_retract", "autoretract", False),
    ("switch.power_pet_door_pet_proximity_keep_open", "cmd_lockout", True),
]


@pytest.mark.parametrize(("entity_id", "field", "inverted"), SWITCH_FIELDS)
@pytest.mark.parametrize("turn_on", [True, False])
async def test_a_switch_change_reaches_the_real_door(
    hass: HomeAssistant,
    simulated_entry: MockConfigEntry,
    simulated_door: DoorSimulator,
    entity_id: str,
    field: str,
    inverted: bool,
    turn_on: bool,
) -> None:
    """Both directions of every switch, read back off the simulator.

    Parametrized over on AND off because a command that sets the field
    unconditionally - or that sends the enable opcode for both - passes a
    one-way test and breaks the moment a user turns something off.
    """
    await hass.services.async_call(
        "switch",
        "turn_on" if turn_on else "turn_off",
        {"entity_id": entity_id},
        blocking=True,
    )
    await hass.async_block_till_done()

    expected = (not turn_on) if inverted else turn_on
    assert getattr(simulated_door.state, field) is expected


async def test_the_pet_proximity_switch_is_not_re_inverted(
    hass: HomeAssistant, simulated_entry: MockConfigEntry, simulated_door: DoorSimulator
) -> None:
    """Stated on its own, because it is the one that has been wrong before.

    "Keep the door open while a pet is near" ON means the door must NOT lock
    out commands. A second inversion here would send the opposite opcode and
    the door would clamp shut on a pet standing in the doorway - which is a
    safety behaviour, not a cosmetic one.
    """
    await hass.services.async_call(
        "switch",
        "turn_on",
        {"entity_id": "switch.power_pet_door_pet_proximity_keep_open"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert simulated_door.state.cmd_lockout is False
    assert hass.states.get("switch.power_pet_door_pet_proximity_keep_open").state == "on"


#: The five notification toggles and the simulator field each one owns.
NOTIFICATION_FIELDS = [
    ("switch.power_pet_door_notify_inside_sensor_on", "sensor_on_indoor"),
    ("switch.power_pet_door_notify_inside_sensor_off", "sensor_off_indoor"),
    ("switch.power_pet_door_notify_outside_sensor_on", "sensor_on_outdoor"),
    ("switch.power_pet_door_notify_outside_sensor_off", "sensor_off_outdoor"),
    ("switch.power_pet_door_notify_low_battery", "low_battery"),
]


@pytest.mark.parametrize(("entity_id", "field"), NOTIFICATION_FIELDS)
@pytest.mark.parametrize("turn_on", [True, False])
async def test_a_notification_switch_reaches_the_real_door(
    hass: HomeAssistant,
    simulated_entry: MockConfigEntry,
    simulated_door: DoorSimulator,
    entity_id: str,
    field: str,
    turn_on: bool,
) -> None:
    """The five settings travel as ONE message, so each must pick its own bit.

    Two switches wired to the same keyword look identical through a mock -
    both "called set_notifications" - and are only distinguishable by
    reading which bit the door ended up with.
    """
    await hass.services.async_call(
        "switch",
        "turn_on" if turn_on else "turn_off",
        {"entity_id": entity_id},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert getattr(simulated_door.state, field) is turn_on


async def test_setting_one_notification_leaves_the_others_alone(
    hass: HomeAssistant, simulated_entry: MockConfigEntry, simulated_door: DoorSimulator
) -> None:
    """One message carries all five, so the other four must be preserved.

    The door has no partial-update command: whatever is sent replaces the
    lot. Sending defaults for the untouched four would silently switch off
    notifications the user had enabled - and they would only find out by not
    being told their battery was flat.
    """
    await hass.services.async_call(
        "switch",
        "turn_on",
        {"entity_id": "switch.power_pet_door_notify_inside_sensor_on"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert simulated_door.state.sensor_on_indoor is True

    await hass.services.async_call(
        "switch",
        "turn_on",
        {"entity_id": "switch.power_pet_door_notify_outside_sensor_off"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert simulated_door.state.sensor_off_outdoor is True
    assert simulated_door.state.sensor_on_indoor is True


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------


async def test_the_hold_open_time_reaches_the_real_door_in_seconds(
    hass: HomeAssistant, simulated_entry: MockConfigEntry, simulated_door: DoorSimulator
) -> None:
    """Seconds on the entity, centiseconds on the wire, seconds in the door.

    The library owns that conversion. Asserting the door's own value is what
    catches a factor-of-100 error, which a mock assertion on the entity's
    argument cannot see at all - it would read 6.0 either way.
    """
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.power_pet_door_hold_open_time", "value": 6.0},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert simulated_door.state.hold_time == 6.0


@pytest.mark.parametrize(
    ("entity_id", "field"),
    [
        ("number.power_pet_door_sensor_trigger_voltage", "sensor_trigger_voltage"),
        (
            "number.power_pet_door_sleep_sensor_trigger_voltage",
            "sleep_sensor_trigger_voltage",
        ),
    ],
)
async def test_a_trigger_voltage_reaches_the_real_door_in_millivolts(
    hass: HomeAssistant,
    simulated_entry: MockConfigEntry,
    simulated_door: DoorSimulator,
    entity_id: str,
    field: str,
) -> None:
    """1.5 V on the dashboard must arrive as 1500 at the door.

    The entity presents volts because that is what HA's VOLTAGE device class
    means; the door counts millivolts. Only the door's own value proves the
    scaling survived the round trip.
    """
    await hass.services.async_call(
        "number", "set_value", {"entity_id": entity_id, "value": 1.5}, blocking=True
    )
    await hass.async_block_till_done()

    assert getattr(simulated_door.state, field) == 1500


# ---------------------------------------------------------------------------
# The timezone select
# ---------------------------------------------------------------------------


async def test_choosing_a_timezone_sends_the_door_a_posix_rule(
    hass: HomeAssistant, simulated_entry: MockConfigEntry, simulated_door: DoorSimulator
) -> None:
    """The door stores POSIX, not IANA.

    Sending "America/New_York" would be stored verbatim and then fail to
    parse as a rule, which silently breaks every schedule on the door -
    the failure is invisible until a window does not open.
    """
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.power_pet_door_timezone", "option": "America/New_York"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert simulated_door.state.timezone == get_posix_tz_string("America/New_York")
    assert "," in simulated_door.state.timezone


# ---------------------------------------------------------------------------
# Buttons and the cover - the motor
# ---------------------------------------------------------------------------


async def test_the_auto_close_button_uses_the_timed_open(
    hass: HomeAssistant, simulated_entry: MockConfigEntry, simulated_door: DoorSimulator
) -> None:
    """HOLDING, not KEEPUP - a genuinely different command.

    This and `cover.open_cover` send different bytes (OPEN vs
    OPEN_AND_HOLD) and a mock accepts either. Asserting that the door
    reaches HOLDING, and then closes itself, is the only way to tell them
    apart - and it is why this one is a button while Open is not.
    """
    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": "button.power_pet_door_open_and_auto_close"},
        blocking=True,
    )

    await simulated_door.wait_for_status(DOOR_STATE_HOLDING, timeout=10)
    assert simulated_door.state.door_status == DOOR_STATE_HOLDING

    # ...and it closes on its own, which is what "auto close" means. The
    # fixture's hold time is 1s, so this is a real transition, not a wait.
    await simulated_door.wait_for_status(DOOR_STATE_CLOSED, timeout=10)
    assert simulated_door.state.door_status == DOOR_STATE_CLOSED


async def test_the_toggle_button_opens_a_closed_real_door(
    hass: HomeAssistant, simulated_entry: MockConfigEntry, simulated_door: DoorSimulator
) -> None:
    """Toggle from closed opens."""
    assert simulated_door.state.door_status == DOOR_STATE_CLOSED

    await hass.services.async_call(
        "button", "press", {"entity_id": "button.power_pet_door_toggle"}, blocking=True
    )

    await simulated_door.wait_for_status(
        (DOOR_STATE_RISING, DOOR_STATE_KEEPUP, DOOR_STATE_HOLDING), timeout=10
    )
    assert simulated_door.state.door_status != DOOR_STATE_CLOSED


async def test_the_toggle_button_closes_an_open_real_door(
    hass: HomeAssistant, simulated_entry: MockConfigEntry, simulated_door: DoorSimulator
) -> None:
    """...and from open, closes.

    The other half of "toggle". A button wired to `open()` satisfies the
    test above and fails this one.
    """
    await simulated_door.open_door(hold=True)
    await simulated_door.wait_for_status(DOOR_STATE_KEEPUP, timeout=10)

    await hass.services.async_call(
        "button", "press", {"entity_id": "button.power_pet_door_toggle"}, blocking=True
    )

    await simulated_door.wait_for_status(DOOR_STATE_CLOSED, timeout=10)
    assert simulated_door.state.door_status == DOOR_STATE_CLOSED


async def test_opening_the_cover_parks_the_real_door_open(
    hass: HomeAssistant, simulated_entry: MockConfigEntry, simulated_door: DoorSimulator
) -> None:
    """The cover holds, so it cannot report open and then close unprompted."""
    await hass.services.async_call(
        "cover", "open_cover", {"entity_id": "cover.power_pet_door_door"}, blocking=True
    )

    await simulated_door.wait_for_status(DOOR_STATE_KEEPUP, timeout=10)
    assert simulated_door.state.door_status == DOOR_STATE_KEEPUP


async def test_closing_the_cover_closes_the_real_door(
    hass: HomeAssistant, simulated_entry: MockConfigEntry, simulated_door: DoorSimulator
) -> None:
    """The cover's close reaches the motor."""
    await simulated_door.open_door(hold=True)
    await simulated_door.wait_for_status(DOOR_STATE_KEEPUP, timeout=10)

    await hass.services.async_call(
        "cover", "close_cover", {"entity_id": "cover.power_pet_door_door"}, blocking=True
    )

    await simulated_door.wait_for_status(DOOR_STATE_CLOSED, timeout=10)
    assert simulated_door.state.door_status == DOOR_STATE_CLOSED


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------


async def test_setting_a_schedule_writes_a_real_slot_on_the_door(
    hass: HomeAssistant, simulated_entry: MockConfigEntry, simulated_door: DoorSimulator
) -> None:
    """The whole schedule write path, end to end on the wire.

    The door requires `index` as a SIBLING of `schedule` in SET_SCHEDULE -
    a message carrying only `schedule` is answered with success:"false" and
    stores nothing. A mock accepts either shape, so only the simulator's
    slot table proves the write actually landed.
    """
    assert simulated_door.state.schedules == {}

    await hass.services.async_call(
        DOMAIN,
        "set_schedule",
        {
            "entity_id": "binary_sensor.power_pet_door_inside_schedule",
            "schedule": {"monday": [{"from": "06:00:00", "to": "20:00:00"}]},
        },
        blocking=True,
    )
    await hass.async_block_till_done()

    assert len(simulated_door.state.schedules) == 1
    stored = next(iter(simulated_door.state.schedules.values()))
    assert stored.inside is True
    assert stored.outside is False
    assert (stored.start_hour, stored.start_min) == (6, 0)
    assert (stored.end_hour, stored.end_min) == (20, 0)
    # days_of_week is [Sun..Sat] on the wire, so Monday is index 1.
    assert stored.days_of_week == [False, True, False, False, False, False, False]


async def test_editing_a_schedule_reuses_the_slot_on_a_real_door(
    hass: HomeAssistant, simulated_entry: MockConfigEntry, simulated_door: DoorSimulator
) -> None:
    """Regression for finding B1, against a real slot table.

    The unit test asserts the index handed to `set_schedule`; this asserts
    what the DOOR ends up holding. Writing the edit to a new slot left the
    old window in place and the door gated the union of both - so the user's
    06:00 window was still in force after they moved it to 07:00. Exactly
    one slot, holding exactly the new window, is the assertion.
    """
    await hass.services.async_call(
        DOMAIN,
        "set_schedule",
        {
            "entity_id": "binary_sensor.power_pet_door_inside_schedule",
            "schedule": {"monday": [{"from": "06:00:00", "to": "20:00:00"}]},
        },
        blocking=True,
    )
    await hass.async_block_till_done()

    await hass.services.async_call(
        DOMAIN,
        "set_schedule",
        {
            "entity_id": "binary_sensor.power_pet_door_inside_schedule",
            "schedule": {"monday": [{"from": "07:00:00", "to": "21:00:00"}]},
        },
        blocking=True,
    )
    await hass.async_block_till_done()

    assert len(simulated_door.state.schedules) == 1
    stored = next(iter(simulated_door.state.schedules.values()))
    assert (stored.start_hour, stored.end_hour) == (7, 21)


async def test_writing_the_inside_schedule_leaves_the_outside_one_on_the_door(
    hass: HomeAssistant, simulated_entry: MockConfigEntry, simulated_door: DoorSimulator
) -> None:
    """One table, two sensors - and editing one must not clear the other.

    Asserted on the door's own slots because the diffing, the slot reuse and
    the flag-clearing all happen across several round trips; a mock shows
    the intent, only the door shows the result.
    """
    await hass.services.async_call(
        DOMAIN,
        "set_schedule",
        {
            "entity_id": "binary_sensor.power_pet_door_outside_schedule",
            "schedule": {"saturday": [{"from": "08:00:00", "to": "22:00:00"}]},
        },
        blocking=True,
    )
    await hass.async_block_till_done()

    await hass.services.async_call(
        DOMAIN,
        "set_schedule",
        {
            "entity_id": "binary_sensor.power_pet_door_inside_schedule",
            "schedule": {"monday": [{"from": "06:00:00", "to": "20:00:00"}]},
        },
        blocking=True,
    )
    await hass.async_block_till_done()

    stored = list(simulated_door.state.schedules.values())
    outside = [entry for entry in stored if entry.outside]
    inside = [entry for entry in stored if entry.inside]

    assert len(outside) == 1
    assert (outside[0].start_hour, outside[0].end_hour) == (8, 22)
    assert len(inside) == 1
    assert (inside[0].start_hour, inside[0].end_hour) == (6, 20)


async def test_clearing_a_schedule_empties_the_slot_on_the_door(
    hass: HomeAssistant, simulated_entry: MockConfigEntry, simulated_door: DoorSimulator
) -> None:
    """An empty payload deletes the slot rather than leaving it behind."""
    await hass.services.async_call(
        DOMAIN,
        "set_schedule",
        {
            "entity_id": "binary_sensor.power_pet_door_inside_schedule",
            "schedule": {"monday": [{"from": "06:00:00", "to": "20:00:00"}]},
        },
        blocking=True,
    )
    await hass.async_block_till_done()
    assert len(simulated_door.state.schedules) == 1

    await hass.services.async_call(
        DOMAIN,
        "set_schedule",
        {"entity_id": "binary_sensor.power_pet_door_inside_schedule", "schedule": {}},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert simulated_door.state.schedules == {}


async def test_one_action_naming_both_schedules_writes_both_of_them(
    hass: HomeAssistant, simulated_entry: MockConfigEntry, simulated_door: DoorSimulator
) -> None:
    """Two entities, one call - and neither write may be lost.

    `set_schedule` is a read-modify-write over a table the door holds ONCE
    for both sensors. With `PARALLEL_UPDATES = 0` Home Assistant gives the
    platform no semaphore and `entity_service_call` gathers the two
    coroutines, so both rebuilt the OTHER kind from the same pre-edit table
    and the last writer resurrected the other's old windows. One write
    vanished, the action reported success, and nothing was logged.

    This is not an exotic shape: naming the DEVICE is what Home Assistant's
    visual action editor produces, and a device target expands to both
    schedule entities.

    Asserted against the simulator's own slots, because the loss only shows
    after the diffing and slot reuse have run across several round trips - a
    mock records the intent, only the door shows the result.
    """
    await hass.services.async_call(
        DOMAIN,
        "set_schedule",
        {
            "entity_id": [
                "binary_sensor.power_pet_door_inside_schedule",
                "binary_sensor.power_pet_door_outside_schedule",
            ],
            "schedule": {"monday": [{"from": "06:00:00", "to": "20:00:00"}]},
        },
        blocking=True,
    )
    await hass.async_block_till_done()

    stored = list(simulated_door.state.schedules.values())
    inside = [entry for entry in stored if entry.inside]
    outside = [entry for entry in stored if entry.outside]

    assert len(inside) == 1, "the inside write was lost"
    assert (inside[0].start_hour, inside[0].end_hour) == (6, 20)
    assert len(outside) == 1, "the outside write was lost"
    assert (outside[0].start_hour, outside[0].end_hour) == (6, 20)


async def test_a_card_save_racing_an_automation_loses_neither(
    hass: HomeAssistant, simulated_entry: MockConfigEntry, simulated_door: DoorSimulator
) -> None:
    """The gap `PARALLEL_UPDATES` cannot close.

    That semaphore serialises two entity-service calls against each other,
    but the Lovelace card does not go through the entity service at all - it
    writes through the WebSocket API. So a card save landing between an
    automation's read and its write still lost one of them, silently, on a
    device that holds one table for both sensors and takes one connection.

    Driven as the two real entry points, started together and awaited
    together, so the interleaving is genuine rather than staged.
    """
    coordinator = simulated_entry.runtime_data

    await asyncio.gather(
        apply_schedule(coordinator, "inside", {"monday": [{"from": "06:00", "to": "20:00"}]}),
        apply_schedule(coordinator, "outside", {"tuesday": [{"from": "09:00", "to": "17:00"}]}),
    )
    await hass.async_block_till_done()

    stored = list(simulated_door.state.schedules.values())
    inside = [entry for entry in stored if entry.inside]
    outside = [entry for entry in stored if entry.outside]

    assert len(inside) == 1, "the inside write was lost"
    assert (inside[0].start_hour, inside[0].end_hour) == (6, 20)
    assert len(outside) == 1, "the outside write was lost"
    assert (outside[0].start_hour, outside[0].end_hour) == (9, 17)
