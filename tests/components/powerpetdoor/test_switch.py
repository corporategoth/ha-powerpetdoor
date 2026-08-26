# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""Switch entities: every toggle, its polarity, and its availability gate."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from powerpetdoor import CommandError, NotificationSettings
from pytest_homeassistant_custom_component.common import MockConfigEntry

#: Every plain switch: entity_id, the door property it reads, the door
#: method it writes, and whether the door being powered off hides it.
#:
#: Listed exhaustively rather than derived from SWITCHES, because deriving
#: it would make the table agree with the code by construction and prove
#: nothing. Entity ids in particular are a contract with the user's
#: dashboard - "switch.power_pet_door_schedule_enabled" is what an
#: automation names, and it is NOT the same string as its key, `auto`.
SWITCHES = [
    ("switch.power_pet_door_power", "power", "set_power", False),
    ("switch.power_pet_door_inside_sensor", "inside_sensor", "set_inside_sensor", True),
    ("switch.power_pet_door_outside_sensor", "outside_sensor", "set_outside_sensor", True),
    ("switch.power_pet_door_schedule_enabled", "auto", "set_auto", True),
    ("switch.power_pet_door_outside_safety_lock", "safety_lock", "set_safety_lock", True),
    ("switch.power_pet_door_auto_retract", "autoretract", "set_autoretract", True),
    (
        "switch.power_pet_door_pet_proximity_keep_open",
        "pet_proximity_keep_open",
        "set_pet_proximity_keep_open",
        True,
    ),
]

#: The five notification toggles. They share one door method taking keyword
#: arguments, so each row names its own keyword - wiring two of them to the
#: same keyword is the mistake this table exists to catch.
NOTIFICATION_SWITCHES = [
    ("switch.power_pet_door_notify_inside_sensor_on", "inside_on"),
    ("switch.power_pet_door_notify_inside_sensor_off", "inside_off"),
    ("switch.power_pet_door_notify_outside_sensor_on", "outside_on"),
    ("switch.power_pet_door_notify_outside_sensor_off", "outside_off"),
    ("switch.power_pet_door_notify_low_battery", "low_battery"),
]


@pytest.fixture(autouse=True)
def _enable_all(entity_registry_enabled_by_default: None) -> None:
    """Most of these switches are diagnostic and off by default."""


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("entity_id", "prop", "_method", "_gated"), SWITCHES)
async def test_each_switch_reports_the_door_setting_it_controls(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    entity_id: str,
    prop: str,
    _method: str,
    _gated: bool,
) -> None:
    """Both states, so an inverted `value_fn` cannot pass.

    Asserting only "on" would pass for a switch wired to the wrong property
    as long as that property happened to be True too - which, with seven
    booleans on one door, it usually is.
    """
    setattr(mock_door, prop, True)
    async_push(hass, mock_door)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "on"

    setattr(mock_door, prop, False)
    async_push(hass, mock_door)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "off"


@pytest.mark.parametrize(("entity_id", "field"), NOTIFICATION_SWITCHES)
async def test_each_notification_switch_reads_its_own_field(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    entity_id: str,
    field: str,
) -> None:
    """Exactly one of the five is on, and it is the right one.

    The five settings arrive as one object, so a switch reading the wrong
    attribute of it is invisible unless the other four are known to be off.
    """
    mock_door.notifications = NotificationSettings(**{field: True})
    async_push(hass, mock_door)
    await hass.async_block_till_done()

    assert hass.states.get(entity_id).state == "on"
    others = [row[0] for row in NOTIFICATION_SWITCHES if row[0] != entity_id]
    assert [hass.states.get(other).state for other in others] == ["off"] * 4


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("entity_id", "_prop", "method", "_gated"), SWITCHES)
@pytest.mark.parametrize(("service", "expected"), [("turn_on", True), ("turn_off", False)])
async def test_each_switch_sends_the_right_value_to_the_door(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    entity_id: str,
    _prop: str,
    method: str,
    _gated: bool,
    service: str,
    expected: bool,
) -> None:
    """Turn on sends True and turn off sends False, per switch.

    The argument is the assertion. A switch that called its setter with a
    constant, or with the value inverted, satisfies "the method was called"
    and would ship - and for `pet_proximity_keep_open`, whose wire form IS
    inverted, that is a mistake with real history.
    """
    await hass.services.async_call("switch", service, {"entity_id": entity_id}, blocking=True)

    getattr(mock_door, method).assert_awaited_once_with(expected)


@pytest.mark.parametrize(("entity_id", "field"), NOTIFICATION_SWITCHES)
@pytest.mark.parametrize(("service", "expected"), [("turn_on", True), ("turn_off", False)])
async def test_each_notification_switch_sets_only_its_own_keyword(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    entity_id: str,
    field: str,
    service: str,
    expected: bool,
) -> None:
    """One keyword, and no others - the door merges what it is sent.

    Sending a second keyword would overwrite a setting the user did not
    touch, so "exactly these kwargs" is the assertion rather than "contains".
    """
    await hass.services.async_call("switch", service, {"entity_id": entity_id}, blocking=True)

    mock_door.set_notifications.assert_awaited_once_with(**{field: expected})


async def test_a_switch_writes_its_new_state_without_waiting_for_the_door(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """The toggle does not spring back under the user's finger.

    The door echoes a change as a push, but not always instantly. Without
    the local update the switch shows its old value until the echo lands,
    which reads as "my tap did nothing".
    """
    mock_door.inside_sensor = True
    assert hass.states.get("switch.power_pet_door_inside_sensor").state == "on"

    # The door has NOT pushed anything back; only the cached property moved,
    # exactly as the library updates it on a successful write.
    mock_door.inside_sensor = False
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.power_pet_door_inside_sensor"}, blocking=True
    )

    assert hass.states.get("switch.power_pet_door_inside_sensor").state == "off"


@pytest.mark.parametrize(("entity_id", "_prop", "method", "_gated"), SWITCHES)
@pytest.mark.parametrize(
    "raised", [CommandError("door said no"), OSError("reset"), TimeoutError("no answer")]
)
async def test_a_switch_reports_a_door_that_refuses(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    entity_id: str,
    _prop: str,
    method: str,
    _gated: bool,
    raised: Exception,
) -> None:
    """A refused write raises a translated error, not a silent no-op.

    Silence here is the worst outcome: the user believes the door is locked
    when it is not.
    """
    getattr(mock_door, method).side_effect = raised

    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call("switch", "turn_on", {"entity_id": entity_id}, blocking=True)

    assert err.value.translation_key == "command_failed"


async def test_a_notification_switch_reports_a_door_that_refuses(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """The notification switches share one setter and one error path."""
    mock_door.set_notifications.side_effect = CommandError("nope")

    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            "switch",
            "turn_on",
            {"entity_id": "switch.power_pet_door_notify_low_battery"},
            blocking=True,
        )

    assert err.value.translation_key == "command_failed"


# ---------------------------------------------------------------------------
# Availability - which switches survive the door being powered off
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("entity_id", "_prop", "_method", "gated"), SWITCHES)
async def test_powering_the_door_off_hides_only_the_motor_dependent_switches(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    entity_id: str,
    _prop: str,
    _method: str,
    gated: bool,
) -> None:
    """The power switch itself must NOT be gated on power.

    Previous versions hid every entity behind `door.power`, which removed
    the very switch needed to turn it back on. `gated` is asserted per row
    rather than as a blanket rule, so both sides of the distinction are
    covered by the same test.
    """
    mock_door.power = False
    async_push(hass, mock_door)
    await hass.async_block_till_done()

    state = hass.states.get(entity_id).state
    if gated:
        assert state == "unavailable"
    else:
        # A real on/off, not merely "not unavailable" - `unknown` would have
        # satisfied that and is just as broken to the user.
        assert state in ("on", "off")


@pytest.mark.parametrize(("entity_id", "_field"), NOTIFICATION_SWITCHES)
async def test_the_notification_switches_survive_the_door_being_powered_off(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    entity_id: str,
    _field: str,
) -> None:
    """The door still remembers these while powered down.

    They are configuration, not motor behaviour, so hiding them would make
    a setting the door is perfectly happy to change look broken.
    """
    mock_door.power = False
    async_push(hass, mock_door)
    await hass.async_block_till_done()

    # A concrete state, not merely "not unavailable": an entity reporting
    # `unknown` is exactly as broken to a user, and the old assertion
    # passed for both.
    assert hass.states.get(entity_id).state in ("on", "off")


# ---------------------------------------------------------------------------
# The connection switch
# ---------------------------------------------------------------------------


async def test_the_connection_switch_reports_whether_the_door_is_connected(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """It replaces the old connectivity binary sensor, so it must report."""
    assert hass.states.get("switch.power_pet_door_connection").state == "on"

    mock_door.connected = False
    for callback in mock_door._callbacks["on_disconnect"]:
        callback()
    await hass.async_block_till_done()

    assert hass.states.get("switch.power_pet_door_connection").state == "off"


async def test_the_connection_switch_stays_available_while_the_door_is_gone(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """The control that gets the connection back cannot itself go away.

    An unavailable connection switch would say nothing about the outage and
    offer no way out of it.
    """
    mock_door.connected = False
    mock_door.power = False
    for callback in mock_door._callbacks["on_disconnect"]:
        callback()
    await hass.async_block_till_done()

    assert hass.states.get("switch.power_pet_door_connection").state == "off"


async def test_turning_the_connection_off_frees_the_door_for_the_phone_app(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """Issue #18: the door accepts one client, so this hands it back."""
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.power_pet_door_connection"}, blocking=True
    )

    mock_door.disconnect.assert_awaited_once()


async def test_turning_the_connection_back_on_reconnects_and_refreshes(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """Everything cached went stale while disconnected.

    Reconnecting without a refresh would leave every entity showing the
    values the door had before the phone app changed them.
    """
    mock_door.connect.reset_mock()
    mock_door.refresh.reset_mock()

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.power_pet_door_connection"}, blocking=True
    )
    await hass.async_block_till_done()

    mock_door.connect.assert_awaited_once()
    mock_door.refresh.assert_awaited()


@pytest.mark.parametrize(
    "raised", [CommandError("busy"), OSError("no route to host"), TimeoutError("no answer")]
)
async def test_a_reconnection_that_fails_is_reported_to_the_user(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock, raised: Exception
) -> None:
    """Turning the switch on when the door is gone says so.

    `cannot_connect`, not `command_failed`: the message names the address,
    which is the one piece of information that makes this actionable.
    """
    mock_door.connect.side_effect = raised

    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": "switch.power_pet_door_connection"}, blocking=True
        )

    assert err.value.translation_key == "cannot_connect"
    assert err.value.translation_placeholders["host"] == "192.0.2.10"


def async_push(hass: HomeAssistant, door: MagicMock) -> None:
    """Fire the door's settings-change callbacks, as a real push would.

    Changing a property on the double is not enough on its own: entities
    only re-read when the coordinator tells them to, which is exactly what
    happens on the wire.
    """
    for callback in door._callbacks["on_settings_change"]:
        callback({})
