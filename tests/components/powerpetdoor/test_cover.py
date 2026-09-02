# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""The cover entity - the flap itself."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from homeassistant.components.cover import CoverEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from powerpetdoor import CommandError, DoorStatus
from pytest_homeassistant_custom_component.common import MockConfigEntry

COVER = "cover.power_pet_door_door"

#: Every door state the cover can RENDER, with the `is_closed`/`is_closing`
#: the library derives from it, the position it reports, and the cover state
#: that must result.
#:
#: `DoorStatus.POWEROFF` is deliberately absent. The cover is a
#: `PowerPetDoorPoweredEntity`, so a switched-off door makes it
#: `unavailable` before any of this is consulted - and a row pairing that
#: status with a powered door would be a state no device can be in. The
#: powered-off case is pinned by
#: `test_the_cover_is_unavailable_while_the_door_is_powered_off` instead.
#:
#: The library's own rules, restated here as a table on purpose: this file
#: tests what cover.py DERIVES (`is_opening`, which the facade does not
#: expose), and that derivation is only meaningful against the two flags it
#: sits beside. tests/simulator/ drives the same transitions through a real
#: door, which is what checks the table itself is not fiction.
STATES = [
    (DoorStatus.IDLE, True, False, 0, "closed"),
    (DoorStatus.CLOSED, True, False, 0, "closed"),
    (DoorStatus.RISING, False, False, 33, "opening"),
    (DoorStatus.SLOWING, False, False, 66, "opening"),
    (DoorStatus.HOLDING, False, False, 100, "open"),
    (DoorStatus.KEEPUP, False, False, 100, "open"),
    # The motor has started and the flap has not moved, so the door is still
    # fully open AND already closing. Omitting it let a mutation that reports
    # CLOSING as *opening* - the flap visibly coming down while the cover says
    # it is going up - pass the whole suite.
    (DoorStatus.CLOSING, False, True, 100, "closing"),
    (DoorStatus.CLOSING_TOP_OPEN, False, True, 66, "closing"),
    (DoorStatus.CLOSING_MID_OPEN, False, True, 33, "closing"),
    # A frame the door sent that the library could not parse. Neither open
    # nor closed nor moving - issue #16 is a real report of exactly this
    # kind of malformed frame, and the cover must not claim the flap is
    # open because it happens not to be closed.
    (DoorStatus.UNKNOWN, False, False, 0, "open"),
]


def push(hass: HomeAssistant, door: MagicMock, status: DoorStatus) -> None:
    """Put the door double into `status`, with consistent derived flags."""
    for candidate, is_closed, is_closing, position, _ in STATES:
        if candidate is status:
            door.status = status
            door.is_closed = is_closed
            door.is_closing = is_closing
            door.is_open = status in (
                DoorStatus.RISING,
                DoorStatus.SLOWING,
                DoorStatus.HOLDING,
                DoorStatus.KEEPUP,
            )
            door.position = position
            break
    for callback in door._callbacks["on_status_change"]:
        callback(status)


@pytest.mark.parametrize(("status", "_c", "_g", "_p", "expected"), STATES)
async def test_every_door_state_maps_to_one_cover_state(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    status: DoorStatus,
    _c: bool,
    _g: bool,
    _p: int,
    expected: str,
) -> None:
    """The whole state machine, one row at a time.

    RISING and SLOWING are the rows this file exists for: the facade has no
    `is_opening`, so cover.py derives it, and a door mid-rise that reported
    "open" would make a wait-for-open automation continue while the flap was
    still moving.
    """
    push(hass, mock_door, status)
    await hass.async_block_till_done()

    assert hass.states.get(COVER).state == expected


@pytest.mark.parametrize(("status", "_c", "_g", "position", "_e"), STATES)
async def test_the_cover_reports_how_far_open_the_flap_is(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    status: DoorStatus,
    _c: bool,
    _g: bool,
    position: int,
    _e: str,
) -> None:
    """Position is what distinguishes a shutter from a plain door.

    A dashboard slider and any position-aware automation read this, and it
    is the only thing that separates SLOWING from RISING to a user.
    """
    push(hass, mock_door, status)
    await hass.async_block_till_done()

    assert hass.states.get(COVER).attributes["current_position"] == position


async def test_the_cover_offers_only_open_and_close(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """No SET_POSITION or STOP: the door has no command for either.

    Advertising a feature the hardware lacks puts a slider on the dashboard
    that silently does nothing.
    """
    features = hass.states.get(COVER).attributes["supported_features"]

    assert features == CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE


async def test_the_cover_is_a_shutter(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Pinned by literal: previous versions shipped SHUTTER too.

    Changing the device class changes the icon, the wording a voice
    assistant uses, and how existing dashboards render it.
    """
    assert hass.states.get(COVER).attributes["device_class"] == "shutter"


async def test_opening_the_cover_holds_the_door_open(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """`open()`, never `cycle()`.

    A cover wired to the timed open would report open and then go closed
    with no command behind it, which no automation could reason about.
    """
    await hass.services.async_call("cover", "open_cover", {"entity_id": COVER}, blocking=True)

    mock_door.open.assert_awaited_once()
    mock_door.cycle.assert_not_awaited()


async def test_closing_the_cover_closes_the_door(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """...and does not toggle, which would open a closed door."""
    await hass.services.async_call("cover", "close_cover", {"entity_id": COVER}, blocking=True)

    mock_door.close.assert_awaited_once()
    mock_door.toggle.assert_not_awaited()


@pytest.mark.parametrize(("service", "method"), [("open_cover", "open"), ("close_cover", "close")])
@pytest.mark.parametrize(
    "raised", [CommandError("obstructed"), OSError("reset"), TimeoutError("no answer")]
)
async def test_a_cover_command_the_door_refuses_is_reported(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    service: str,
    method: str,
    raised: Exception,
) -> None:
    """An obstructed or unreachable door says so rather than failing silently."""
    getattr(mock_door, method).side_effect = raised

    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call("cover", service, {"entity_id": COVER}, blocking=True)

    assert err.value.translation_key == "command_failed"


async def test_the_cover_is_unavailable_while_the_door_is_powered_off(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """A flap with no power to its motor has no meaningful state."""
    mock_door.power = False
    for callback in mock_door._callbacks["on_settings_change"]:
        callback({})
    await hass.async_block_till_done()

    assert hass.states.get(COVER).state == "unavailable"


async def test_the_cover_is_available_on_a_powered_door(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """The other side of the gate."""
    # A concrete state, not merely "not unavailable": an entity reporting
    # `unknown` is exactly as broken to a user, and the old assertion
    # passed for both.
    assert hass.states.get(COVER).state == "closed"
