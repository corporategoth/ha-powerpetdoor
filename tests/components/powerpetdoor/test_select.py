# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""The timezone select.

The door stores a POSIX TZ string and the mapping to IANA names is
many-to-one - every US Eastern zone produces `EST5EDT,M3.2.0,M11.1.0`. So
`current_option` answers a question with four possible sources, and which
one wins is the whole behaviour of this entity.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from powerpetdoor import CommandError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.powerpetdoor.tz_utils import (
    HA_TIMEZONE_OPTION,
    async_init_timezone_cache,
    get_available_timezones,
    get_posix_tz_string,
)

TIMEZONE = "select.power_pet_door_timezone"

# Both produce the SAME POSIX string, which is what makes the "remember what
# the user picked" behaviour necessary rather than decorative.
EASTERN_POSIX = "EST5EDT,M3.2.0,M11.1.0"
NEW_YORK = "America/New_York"
TORONTO = "America/Toronto"


@pytest.fixture(autouse=True)
def _enable_all(entity_registry_enabled_by_default: None) -> None:
    """The timezone select is disabled by default."""


@pytest.fixture(autouse=True)
async def _warm_timezone_cache() -> None:
    """Build the IANA cache before a test reads it.

    Setting the entry up does this too, but the pure-helper tests below do
    not go through setup and would otherwise see an empty option list.
    """
    await async_init_timezone_cache()


def push(door: MagicMock) -> None:
    """Fire the door's settings-change callbacks, as a real push would."""
    for callback in door._callbacks["on_settings_change"]:
        callback({})


# ---------------------------------------------------------------------------
# The option list
# ---------------------------------------------------------------------------


async def test_the_home_assistant_option_is_offered_first(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """The Home Assistant option heads the list.

    It is the option almost everyone wants, and a list of 500-odd IANA names
    with it buried alphabetically is a list nobody finds it in.
    """
    options = hass.states.get(TIMEZONE).attributes["options"]

    assert options[0] == HA_TIMEZONE_OPTION
    assert HA_TIMEZONE_OPTION == "Use Home Assistant timezone"


async def test_the_option_list_carries_real_iana_names(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """The rest of the list is the IANA database, not a hand-written subset."""
    options = hass.states.get(TIMEZONE).attributes["options"]

    assert NEW_YORK in options
    assert "Europe/London" in options
    assert len(options) > 100


async def test_the_helper_puts_the_home_assistant_option_before_every_zone(
    hass: HomeAssistant,
) -> None:
    """The list builder itself, without an entity in the way.

    Two things were wrong here. The assertion was
    `sorted(...) or NEW_YORK in ...`, which accepts two different outcomes and
    so cannot fail - the project's own test rules 1 and 2, broken verbatim.
    And it was the module's only SYNC test while the cache-warming fixture is
    `async def`, so run on its own it asserted
    `["Use Home Assistant timezone"][0] == "Use Home Assistant timezone"` in a
    quarter of a second against an empty zone list.

    Made async so the cache is actually warmed, and each property asserted on
    its own: the sentinel comes first, the rest are sorted, and the list holds
    real zones rather than being empty.
    """
    options = get_available_timezones()

    assert options[0] == HA_TIMEZONE_OPTION
    assert len(options) > 100, "the timezone cache was not warmed"
    assert NEW_YORK in options[1:]
    assert options[1:] == sorted(options[1:])
    assert HA_TIMEZONE_OPTION not in options[1:]


# ---------------------------------------------------------------------------
# current_option - the four sources, in priority order
# ---------------------------------------------------------------------------


async def test_a_door_with_no_timezone_reports_nothing(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """An empty string is "unknown", not a zone called "".

    A door reports this before its first settings refresh, and showing a
    blank as a selected option would let the user "confirm" it back.
    """
    mock_door.timezone = ""
    push(mock_door)
    await hass.async_block_till_done()

    assert hass.states.get(TIMEZONE).state == "unknown"


async def test_the_zone_the_user_picked_wins_while_the_door_still_agrees(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """Picking Toronto must not snap back to New York.

    Both derive the same POSIX string, so without remembering the choice the
    next refresh would silently replace the user's selection with a
    different city - which looks like the setting did not save.
    """
    await hass.services.async_call(
        "select", "select_option", {"entity_id": TIMEZONE, "option": TORONTO}, blocking=True
    )
    mock_door.timezone = get_posix_tz_string(TORONTO)
    push(mock_door)
    await hass.async_block_till_done()

    assert hass.states.get(TIMEZONE).state == TORONTO


async def test_a_remembered_zone_is_dropped_once_the_door_disagrees(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """The other side of that: changed elsewhere, the memory must not lie.

    Someone editing the zone from the phone app is the case. Reporting the
    remembered choice forever would show a zone the door is no longer in.
    """
    await hass.services.async_call(
        "select", "select_option", {"entity_id": TIMEZONE, "option": TORONTO}, blocking=True
    )

    mock_door.timezone = get_posix_tz_string("Europe/London")
    push(mock_door)
    await hass.async_block_till_done()

    assert hass.states.get(TIMEZONE).state != TORONTO


async def test_home_assistants_own_zone_is_reported_by_its_real_name(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """Never as the write-only "use Home Assistant timezone" option.

    That option is an instruction, not a state the door can be in, so
    reporting it back would make the entity's own value un-selectable and
    would hide which zone the door is actually in.
    """
    await hass.config.async_update(time_zone=NEW_YORK)
    mock_door.timezone = EASTERN_POSIX
    push(mock_door)
    await hass.async_block_till_done()

    assert hass.states.get(TIMEZONE).state == NEW_YORK


async def test_any_matching_iana_name_is_reported_when_nothing_better_matches(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """Third fallback: a name that produces the door's POSIX string.

    Home Assistant is set somewhere unrelated and the user has picked
    nothing, so the only thing left is a reverse lookup - and it must
    produce a name the dropdown actually contains, not a raw POSIX string.
    """
    await hass.config.async_update(time_zone="Australia/Sydney")
    mock_door.timezone = EASTERN_POSIX
    push(mock_door)
    await hass.async_block_till_done()

    state = hass.states.get(TIMEZONE)
    assert state.state in state.attributes["options"]
    assert get_posix_tz_string(state.state) == EASTERN_POSIX


async def test_an_unrecognised_posix_string_is_shown_raw(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """Last resort: report what the door holds rather than nothing.

    A door with a custom or corrupt TZ rule has no IANA name, so
    `current_option` returns the POSIX string itself. Home Assistant renders
    an option outside the list as `unknown` - accurate, because it IS an
    invalid selection - so the STATE cannot tell this apart from a door that
    reported nothing at all. `current_option` and the `posix_tz` attribute
    can, and both are asserted: returning None here instead would make a
    misconfigured door indistinguishable from a fresh one in every view.
    """
    mock_door.timezone = "XYZ-99BADRULE"
    push(mock_door)
    await hass.async_block_till_done()

    entity = hass.data["entity_components"]["select"].get_entity(TIMEZONE)
    assert entity.current_option == "XYZ-99BADRULE"

    state = hass.states.get(TIMEZONE)
    assert state.state == "unknown"
    assert state.attributes["posix_tz"] == "XYZ-99BADRULE"


async def test_the_raw_posix_string_is_always_exposed_as_an_attribute(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """The IANA name is a guess; the POSIX string is the fact.

    Many zones share one POSIX rule, so the attribute is the only place a
    user or a bug report can see what the door literally stores.
    """
    mock_door.timezone = EASTERN_POSIX
    push(mock_door)
    await hass.async_block_till_done()

    assert hass.states.get(TIMEZONE).attributes["posix_tz"] == EASTERN_POSIX


# ---------------------------------------------------------------------------
# Selecting
# ---------------------------------------------------------------------------


async def test_selecting_a_zone_sends_its_posix_rule_to_the_door(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """The door speaks POSIX; sending it "America/New_York" sets nothing."""
    await hass.services.async_call(
        "select", "select_option", {"entity_id": TIMEZONE, "option": NEW_YORK}, blocking=True
    )

    mock_door.set_timezone.assert_awaited_once_with(get_posix_tz_string(NEW_YORK))
    assert mock_door.set_timezone.await_args.args[0] == EASTERN_POSIX


async def test_selecting_the_home_assistant_option_sends_home_assistants_zone(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """It resolves to whatever HA is set to at that moment."""
    await hass.config.async_update(time_zone="Europe/London")

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": TIMEZONE, "option": HA_TIMEZONE_OPTION},
        blocking=True,
    )

    mock_door.set_timezone.assert_awaited_once_with(get_posix_tz_string("Europe/London"))


async def test_the_home_assistant_option_is_not_remembered_as_a_selection(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """It is an instruction, so the entity reports the resulting real zone.

    Remembering it would make `current_option` return a string that is not a
    zone, which no template or automation could act on.
    """
    await hass.config.async_update(time_zone=NEW_YORK)

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": TIMEZONE, "option": HA_TIMEZONE_OPTION},
        blocking=True,
    )
    mock_door.timezone = EASTERN_POSIX
    push(mock_door)
    await hass.async_block_till_done()

    assert hass.states.get(TIMEZONE).state == NEW_YORK


async def test_a_zone_that_is_not_on_the_list_never_reaches_the_door(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """Home Assistant rejects an unlisted option before our handler runs.

    Asserted because the option list is the ONLY thing standing between a
    scripted `select.select_option` and an arbitrary string being turned
    into a TZ rule for the door - `_valid_option_or_raise` in HA core is
    load-bearing here, not decorative. The error is HA's own, so only the
    type and the door being untouched are pinned; the wording belongs to
    core, not to strings.json.
    """
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": TIMEZONE, "option": "Mars/Olympus_Mons"},
            blocking=True,
        )

    mock_door.set_timezone.assert_not_awaited()


async def test_the_home_assistant_option_is_refused_when_home_assistant_has_no_zone(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """A Home Assistant with no timezone cannot lend one.

    The placeholder says "unset" rather than naming an empty string, so the
    message reads as a sentence.
    """
    hass.config.time_zone = ""

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": TIMEZONE, "option": HA_TIMEZONE_OPTION},
            blocking=True,
        )

    assert err.value.translation_key == "unknown_timezone"
    assert err.value.translation_placeholders == {"timezone": "unset"}
    mock_door.set_timezone.assert_not_awaited()


@pytest.mark.parametrize(
    "raised", [CommandError("rejected"), OSError("reset"), TimeoutError("no answer")]
)
async def test_a_timezone_the_door_refuses_is_reported_to_the_user(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock, raised: Exception
) -> None:
    """A refused write raises rather than appearing to succeed."""
    mock_door.set_timezone.side_effect = raised

    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            "select", "select_option", {"entity_id": TIMEZONE, "option": NEW_YORK}, blocking=True
        )

    assert err.value.translation_key == "command_failed"


async def test_a_refused_selection_is_not_remembered(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """The entity must not claim a zone the door rejected.

    `self._selected` is assigned only after the write succeeds. Setting it
    first would make `current_option` report the failed choice for as long
    as the door's POSIX string happened to match it.
    """
    mock_door.timezone = EASTERN_POSIX
    mock_door.set_timezone.side_effect = CommandError("rejected")

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "select", "select_option", {"entity_id": TIMEZONE, "option": TORONTO}, blocking=True
        )
    push(mock_door)
    await hass.async_block_till_done()

    assert hass.states.get(TIMEZONE).state != TORONTO


async def test_the_timezone_select_stays_available_while_the_door_is_powered_off(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """The door keeps its clock configuration while powered down."""
    mock_door.power = False
    push(mock_door)
    await hass.async_block_till_done()

    state = hass.states.get(TIMEZONE)
    assert state.state not in ("unavailable", "unknown")
    # A select whose current value is not one of its own options is invalid
    # in Home Assistant, so this is the assertion that decides something.
    # The exact zone is deliberately not pinned: several IANA names share
    # one POSIX rule, and which one is chosen is the mapping's business,
    # tested where the mapping is.
    assert state.state in state.attributes["options"]
