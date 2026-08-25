# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""Button entities: four door commands that must stay four."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from powerpetdoor import CommandError
from pytest_homeassistant_custom_component.common import MockConfigEntry

#: entity_id, the door method it must call, and the three it must NOT.
#:
#: The entity ids are pinned by literal because they are what an automation
#: names, and "open_and_auto_close" is deliberately not its key (`cycle`).
#:
#: There is no Open or Close button, and that absence is asserted below.
#: `door.open()` and `door.close()` are exactly what `cover.open_cover` and
#: `cover.close_cover` already call, so buttons for them would be a second
#: control for the same two actions.
BUTTONS = [
    ("button.power_pet_door_open_and_auto_close", "cycle"),
    ("button.power_pet_door_toggle", "toggle"),
]

#: Still all four: a button must call ITS method and none of the others,
#: and `open`/`close` staying untouched is the assertion that the cover's
#: two actions did not sneak back in under another button's press handler.
ALL_METHODS = {"open", "close", "cycle", "toggle"}


@pytest.mark.parametrize(("entity_id", "method"), BUTTONS)
async def test_each_button_sends_its_own_command_and_no_other(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    entity_id: str,
    method: str,
) -> None:
    """Four buttons, four distinct commands.

    The exclusion is the point. `open` and `cycle` are different bytes on
    the wire - one parks the door open, the other closes itself on a timer -
    and the previous integration conflated them into a single button whose
    behaviour depended on the door's state. Asserting only "the right method
    was called" would pass an implementation that called two of them.
    """
    await hass.services.async_call("button", "press", {"entity_id": entity_id}, blocking=True)

    getattr(mock_door, method).assert_awaited_once()
    for other in ALL_METHODS - {method}:
        getattr(mock_door, other).assert_not_awaited()


@pytest.mark.parametrize(("entity_id", "method"), BUTTONS)
@pytest.mark.parametrize(
    "raised", [CommandError("door said no"), OSError("reset"), TimeoutError("no answer")]
)
async def test_a_button_reports_a_door_that_refuses_the_command(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    entity_id: str,
    method: str,
    raised: Exception,
) -> None:
    """A failed press raises a translated error rather than appearing to work.

    A button that silently swallows a failure is worse than one that errors:
    the user believes the door opened.
    """
    getattr(mock_door, method).side_effect = raised

    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call("button", "press", {"entity_id": entity_id}, blocking=True)

    assert err.value.translation_key == "command_failed"


@pytest.mark.parametrize(("entity_id", "_method"), BUTTONS)
async def test_every_button_is_unavailable_while_the_door_is_powered_off(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    entity_id: str,
    _method: str,
) -> None:
    """The motor does nothing while powered down, so pressing is a fiction.

    Every one of these drives the motor, so unlike the switches there is no
    ungated button - and offering an Open button that cannot open is how a
    user concludes the integration is broken.
    """
    mock_door.power = False
    for callback in mock_door._callbacks["on_settings_change"]:
        callback({})
    await hass.async_block_till_done()

    assert hass.states.get(entity_id).state == "unavailable"


@pytest.mark.parametrize(("entity_id", "_method"), BUTTONS)
async def test_every_button_is_available_on_a_powered_connected_door(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    entity_id: str,
    _method: str,
) -> None:
    """The other side of the gate.

    Without this, a base class that reported everything unavailable would
    satisfy the test above.
    """
    # `unknown` is a button's real resting state - it reports the last press
    # and there has not been one - so that is what to assert. "Not
    # unavailable" also accepted `unknown`, which made the two
    # indistinguishable and the gate meaningless.
    assert hass.states.get(entity_id).state == "unknown"


async def test_the_cover_s_own_two_actions_are_not_also_buttons(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """No Open button, no Close button - the cover is where those live.

    `door.open()` and `door.close()` are precisely what `cover.open_cover`
    and `cover.close_cover` call, so a button for either is a second control
    for the same action: one more thing to keep in sync on a dashboard, and
    one more pair of entities for an automation author to pick the wrong one
    of. Asserted by literal because deleting a button is a breaking change
    and re-adding one silently is the same change in reverse.
    """
    buttons = {
        item.entity_id
        for item in er.async_entries_for_config_entry(entity_registry, setup_integration.entry_id)
        if item.domain == "button"
    }

    assert buttons == {
        "button.power_pet_door_open_and_auto_close",
        "button.power_pet_door_toggle",
    }
