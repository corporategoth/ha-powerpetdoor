# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""The `powerpetdoor/schedule/*` WebSocket API.

This is the integration's only inbound surface: any logged-in Home Assistant
user can reach it, and the Lovelace card in www/ is its only intended
caller. Two things are therefore asserted everywhere below - that a
well-formed call does exactly what the card expects, and that a malformed or
unauthorised one is refused with a specific error code rather than raising
out of a handler.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from homeassistant.components.websocket_api import const as ws_const
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from powerpetdoor import CommandError, Schedule, ScheduleTime
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.powerpetdoor.const import (
    DOMAIN,
    WS_SCHEDULE_GET,
    WS_SCHEDULE_LIST,
    WS_SCHEDULE_UPDATE,
)

from .conftest import TEST_HOST, TEST_PORT

INSIDE = "binary_sensor.power_pet_door_inside_schedule"
OUTSIDE = "binary_sensor.power_pet_door_outside_schedule"


def _mon_fri_six_to_eight(index: int = 0) -> Schedule:
    """Mon-Fri 06:00-20:00, inside only.

    `days_of_week` is indexed from SUNDAY, so this is
    [Sun, Mon, Tue, Wed, Thu, Fri, Sat] with the five weekdays set.
    """
    return Schedule(
        index=index,
        enabled=True,
        days_of_week=[False, True, True, True, True, True, False],
        inside=True,
        outside=False,
        start=ScheduleTime(6, 0),
        end=ScheduleTime(20, 0),
    )


# ---------------------------------------------------------------------------
# The command names themselves
# ---------------------------------------------------------------------------


def test_the_command_names_are_the_ones_the_card_sends() -> None:
    """Pinned by literal: these strings are a contract with every dashboard.

    The card in www/ hardcodes them (`type: 'powerpetdoor/schedule/get'`).
    Deriving them from DOMAIN here and asserting the derivation would pass
    while the card broke, so the literal is the point.
    """
    assert WS_SCHEDULE_LIST == "powerpetdoor/schedule/list"
    assert WS_SCHEDULE_GET == "powerpetdoor/schedule/get"
    assert WS_SCHEDULE_UPDATE == "powerpetdoor/schedule/update"


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


async def test_list_returns_both_schedule_entities_for_one_door(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """One door exposes exactly the inside and the outside schedule.

    The card populates its entity picker from this, so a missing kind means
    a schedule the user cannot reach at all.
    """
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": WS_SCHEDULE_LIST})
    result = await client.receive_json()

    assert result["success"] is True
    assert {row["entity_id"] for row in result["result"]} == {INSIDE, OUTSIDE}
    assert {row["kind"] for row in result["result"]} == {"inside", "outside"}


async def test_list_covers_every_configured_door(
    hass: HomeAssistant,
    two_doors: tuple[MockConfigEntry, MagicMock, MockConfigEntry, MagicMock],
    hass_ws_client: WebSocketGenerator,
) -> None:
    """With two doors, all four schedule entities are listed.

    The commands are registered once against `hass`, not per entry, so this
    is the assertion that they resolve the door from the message rather than
    from whichever entry happened to register them.
    """
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": WS_SCHEDULE_LIST})
    result = await client.receive_json()

    assert len(result["result"]) == 4
    assert len({row["entity_id"] for row in result["result"]}) == 4


async def test_list_skips_an_entity_it_cannot_resolve(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """A registry row that looks like ours but is not is passed over.

    The list filters on platform and a `_schedule` unique_id suffix, which a
    `sensor` entity of ours could also satisfy. Resolving it would hand the
    card an entity_id whose `get` then fails, so it is dropped here instead.
    """
    entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{TEST_HOST}:{TEST_PORT}-decoy_schedule",
        config_entry=setup_integration,
        suggested_object_id="decoy_schedule",
    )
    await hass.async_block_till_done()

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": WS_SCHEDULE_LIST})
    result = await client.receive_json()

    assert {row["entity_id"] for row in result["result"]} == {INSIDE, OUTSIDE}


async def test_list_reports_the_schedule_the_door_actually_holds(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """The payload carries the windows, not just the entity ids."""
    mock_door.schedules = [_mon_fri_six_to_eight()]

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": WS_SCHEDULE_LIST})
    result = await client.receive_json()

    inside = next(row for row in result["result"] if row["kind"] == "inside")
    assert inside["schedule"]["monday"] == [{"from": "06:00", "to": "20:00"}]
    assert inside["schedule_count"] == 5
    # The outside sensor is ungated by that entry, so its schedule is empty -
    # asserting this is what proves the two kinds are read separately.
    outside = next(row for row in result["result"] if row["kind"] == "outside")
    assert outside["schedule"] == {}
    assert outside["schedule_count"] == 0


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


async def test_get_returns_one_schedule_with_its_kind(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """`kind` is what the card titles itself with (finding Fm4).

    The card used to sniff the entity_id for the word "inside", so a door
    named "Inside Porch" made the OUTSIDE card announce itself as the inside
    sensor. The API supplying `kind` is what fixed that, so it must be here.
    """
    mock_door.schedules = [_mon_fri_six_to_eight()]

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": WS_SCHEDULE_GET, "entity_id": INSIDE})
    result = await client.receive_json()

    assert result["success"] is True
    assert result["result"]["kind"] == "inside"
    assert result["result"]["entity_id"] == INSIDE
    assert result["result"]["schedule"]["friday"] == [{"from": "06:00", "to": "20:00"}]


async def test_the_count_totals_windows_not_days(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """Two windows on ONE day count as two.

    Every fixture here has one window per day, where `sum(len(slots))` and
    `len(schedule)` agree - so this field could have been counting DAYS and
    nothing would have known. The card reads it for its collapsed summary,
    so a user letting the cat out morning and evening on a Monday would have
    read "1 time slot" for two.

    The same gap was closed on the entity's attribute in round 4 and missed
    here, which is the third time a multi-site fix has landed at one site
    short.
    """
    mock_door.schedules = [
        Schedule(
            index=0,
            enabled=True,
            days_of_week=[False, True, False, False, False, False, False],
            inside=True,
            outside=False,
            start=ScheduleTime(6, 0),
            end=ScheduleTime(9, 0),
        ),
        Schedule(
            index=1,
            enabled=True,
            days_of_week=[False, True, False, False, False, False, False],
            inside=True,
            outside=False,
            start=ScheduleTime(17, 0),
            end=ScheduleTime(20, 0),
        ),
    ]

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": WS_SCHEDULE_GET, "entity_id": INSIDE})
    result = (await client.receive_json())["result"]

    assert result["schedule_count"] == 2
    assert len(result["schedule"]["monday"]) == 2
    assert len(result["schedule"]) == 1  # ...still one DAY


async def test_get_reports_whether_the_door_is_applying_schedules(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """The card cannot tell from the windows alone whether they are in force.

    With the door's master switch off it consults NO window and both sensors
    stay live around the clock. The stored schedule is unchanged, so a card
    that only receives the windows draws a restriction that is not being
    applied - and every edit the user makes to that grid changes nothing they
    can observe. Measured on firmware 1.7.18, where this is the state a real
    door was found in.
    """
    client = await hass_ws_client(hass)

    mock_door.auto = True
    await client.send_json_auto_id({"type": WS_SCHEDULE_GET, "entity_id": INSIDE})
    assert (await client.receive_json())["result"]["timers_enabled"] is True

    mock_door.auto = False
    await client.send_json_auto_id({"type": WS_SCHEDULE_GET, "entity_id": INSIDE})
    assert (await client.receive_json())["result"]["timers_enabled"] is False


async def test_list_reports_it_too_so_the_picker_agrees_with_the_card(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """Both commands share one payload builder, so both carry it."""
    mock_door.auto = False

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": WS_SCHEDULE_LIST})
    result = await client.receive_json()

    assert result["result"]
    assert all(row["timers_enabled"] is False for row in result["result"])


async def test_get_rejects_an_entity_that_is_not_a_schedule(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """One of OUR binary sensors that is not a schedule is still refused.

    `mains_power` shares the platform and the domain, so it passes every
    check except the unique_id suffix. That suffix is the only thing
    standing between the card and a coordinator lookup for a kind that does
    not exist.
    """
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": WS_SCHEDULE_GET, "entity_id": "binary_sensor.power_pet_door_mains_power"}
    )
    result = await client.receive_json()

    assert result["success"] is False
    assert result["error"]["code"] == ws_const.ERR_NOT_FOUND


async def test_get_rejects_an_entity_belonging_to_another_integration(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """A foreign entity whose id ends in `_schedule` is refused.

    Home Assistant's own `schedule` helper produces exactly such ids, and
    the card's editor dropdown once listed them. Resolving one would reach
    for `runtime_data` on an entry that has no coordinator.
    """
    entity_registry.async_get_or_create(
        "binary_sensor",
        "some_other_integration",
        "abc-inside_schedule",
        suggested_object_id="foreign_inside_schedule",
    )
    await hass.async_block_till_done()

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": WS_SCHEDULE_GET, "entity_id": "binary_sensor.foreign_inside_schedule"}
    )
    result = await client.receive_json()

    assert result["success"] is False
    assert result["error"]["code"] == ws_const.ERR_NOT_FOUND


async def test_get_rejects_an_entity_in_the_wrong_domain(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """Our platform, our suffix, but a `sensor` - still refused.

    The domain check is separate from the platform check, and only this
    asserts it: a sensor of ours could carry an `-inside_schedule` unique_id
    and would otherwise resolve to a real coordinator and a real kind.
    """
    entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{TEST_HOST}:{TEST_PORT}-inside_schedule",
        config_entry=setup_integration,
        suggested_object_id="wrong_domain_inside_schedule",
    )
    await hass.async_block_till_done()

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": WS_SCHEDULE_GET, "entity_id": "sensor.wrong_domain_inside_schedule"}
    )
    result = await client.receive_json()

    assert result["success"] is False
    assert result["error"]["code"] == ws_const.ERR_NOT_FOUND


async def test_get_rejects_an_entity_with_no_config_entry_behind_it(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """A registry row orphaned from its config entry cannot be served.

    Registry rows outlive the entry that made them (an entry removed while
    Home Assistant was stopped). Reaching for `runtime_data` on the None
    that lookup returns would be an AttributeError inside a WebSocket
    handler, which the frontend shows as an unexplained "unknown error".
    """
    entity_registry.async_get_or_create(
        "binary_sensor",
        DOMAIN,
        f"{TEST_HOST}:{TEST_PORT}-orphan_inside_schedule",
        suggested_object_id="orphan_inside_schedule",
    )
    await hass.async_block_till_done()

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": WS_SCHEDULE_GET, "entity_id": "binary_sensor.orphan_inside_schedule"}
    )
    result = await client.receive_json()

    assert result["success"] is False
    assert result["error"]["code"] == ws_const.ERR_NOT_FOUND


async def test_get_rejects_an_entity_whose_entry_is_not_set_up(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """An entry that never finished setup has no coordinator to read.

    This is the state a door left unplugged is in: the entry exists, its
    entities are in the registry from last time, and `runtime_data` was
    never assigned. The card must get a clean "not found", not a crash.
    """
    unloaded = MockConfigEntry(
        domain=DOMAIN,
        title="Asleep",
        unique_id="192.0.2.99:3000",
        data={"host": "192.0.2.99", "port": 3000, "name": "Asleep"},
    )
    unloaded.add_to_hass(hass)
    entity_registry.async_get_or_create(
        "binary_sensor",
        DOMAIN,
        "192.0.2.99:3000-inside_schedule",
        config_entry=unloaded,
        suggested_object_id="asleep_inside_schedule",
    )
    await hass.async_block_till_done()

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": WS_SCHEDULE_GET, "entity_id": "binary_sensor.asleep_inside_schedule"}
    )
    result = await client.receive_json()

    assert result["success"] is False
    assert result["error"]["code"] == ws_const.ERR_NOT_FOUND


async def test_get_rejects_an_entity_id_that_does_not_exist(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """An entity_id with no registry row at all is refused."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": WS_SCHEDULE_GET, "entity_id": "binary_sensor.nope"})
    result = await client.receive_json()

    assert result["success"] is False
    assert result["error"]["code"] == ws_const.ERR_NOT_FOUND


async def test_get_requires_an_entity_id(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """The schema rejects the call before the handler runs."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": WS_SCHEDULE_GET})
    result = await client.receive_json()

    assert result["success"] is False
    assert result["error"]["code"] == ws_const.ERR_INVALID_FORMAT


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


async def test_update_writes_the_schedule_and_returns_the_new_one(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """A save reaches the door and the card gets the door's view back.

    Returning the fresh payload is what lets the card show the saved state
    rather than optimistically keeping what the user drew (finding F8).
    """
    written: list[Schedule] = []

    async def _set(schedule: Schedule) -> None:
        written.append(schedule)

    mock_door.set_schedule.side_effect = _set

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": WS_SCHEDULE_UPDATE,
            "entity_id": INSIDE,
            "schedule": {"monday": [{"from": "06:00", "to": "20:00"}]},
        }
    )
    result = await client.receive_json()

    assert result["success"] is True
    assert len(written) == 1
    assert written[0].start == ScheduleTime(6, 0)
    assert written[0].end == ScheduleTime(20, 0)
    assert written[0].inside is True
    assert written[0].outside is False


async def test_update_is_refused_for_a_non_admin_user(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    hass_ws_client: WebSocketGenerator,
    hass_read_only_access_token: str,
) -> None:
    """Only an admin may change the door's schedule.

    The read-only user can still `get` (asserted below) - the restriction is
    on mutation, which is what `require_admin` means and what the card's
    read-only mode reflects in the UI.
    """
    client = await hass_ws_client(hass, hass_read_only_access_token)
    await client.send_json_auto_id(
        {
            "type": WS_SCHEDULE_UPDATE,
            "entity_id": INSIDE,
            "schedule": {"monday": [{"from": "06:00", "to": "20:00"}]},
        }
    )
    result = await client.receive_json()

    assert result["success"] is False
    assert result["error"]["code"] == ws_const.ERR_UNAUTHORIZED
    mock_door.set_schedule.assert_not_awaited()


async def test_a_non_admin_user_can_still_read_a_schedule(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    hass_read_only_access_token: str,
) -> None:
    """The other side of the admin boundary: reads are open to everyone.

    Without this, `require_admin` on the read commands too would be
    indistinguishable, and a non-admin's dashboard would show an empty card
    rather than a read-only one.
    """
    client = await hass_ws_client(hass, hass_read_only_access_token)
    await client.send_json_auto_id({"type": WS_SCHEDULE_GET, "entity_id": INSIDE})
    result = await client.receive_json()

    assert result["success"] is True
    assert result["result"]["kind"] == "inside"


async def test_update_rejects_an_entity_that_is_not_a_schedule(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """A wrong target is refused BEFORE anything is written to the door."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": WS_SCHEDULE_UPDATE,
            "entity_id": "binary_sensor.power_pet_door_mains_power",
            "schedule": {"monday": [{"from": "06:00", "to": "20:00"}]},
        }
    )
    result = await client.receive_json()

    assert result["success"] is False
    assert result["error"]["code"] == ws_const.ERR_NOT_FOUND
    mock_door.set_schedule.assert_not_awaited()


async def test_update_reports_a_door_that_refuses_the_write(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """A door error becomes an `update_failed` result, not a dropped message.

    The card shows this in a toast and reloads from the device (finding F7),
    so the error has to arrive as a failed result with a message - a handler
    that raised would leave the card's promise pending forever.
    """
    mock_door.set_schedule.side_effect = CommandError("slot table full")

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": WS_SCHEDULE_UPDATE,
            "entity_id": INSIDE,
            "schedule": {"monday": [{"from": "06:00", "to": "20:00"}]},
        }
    )
    result = await client.receive_json()

    assert result["success"] is False
    assert result["error"]["code"] == "update_failed"
    assert "slot table full" in result["error"]["message"]


async def test_update_reports_a_door_that_dropped_off_mid_write(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """A socket error during the write is reported the same way.

    Separate from CommandError on purpose: they arrive from different layers
    and only one `except` tuple catches both. A door losing WiFi mid-save is
    the commonest of the two in practice.
    """
    mock_door.refresh_schedules.side_effect = OSError("connection reset by peer")

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": WS_SCHEDULE_UPDATE,
            "entity_id": INSIDE,
            "schedule": {"monday": [{"from": "06:00", "to": "20:00"}]},
        }
    )
    result = await client.receive_json()

    assert result["success"] is False
    assert result["error"]["code"] == "update_failed"


@pytest.mark.parametrize(
    ("payload", "why"),
    [
        ({"funday": [{"from": "06:00", "to": "20:00"}]}, "unknown day name"),
        ({"monday": [{"from": "06:00"}]}, "slot missing 'to'"),
        ({"monday": [{"to": "20:00"}]}, "slot missing 'from'"),
        ({"monday": {"from": "06:00", "to": "20:00"}}, "mapping where a list belongs"),
        ({"monday": [7]}, "integer where a slot belongs"),
        ({"monday": [{"from": "24:00", "to": "20:00"}]}, "hour 24 is not a time"),
        ({"monday": [{"from": "06:00", "to": "23:60"}]}, "minute 60 is not a time"),
        ({"monday": [{"from": "6:00", "to": "20:00"}]}, "unpadded hour"),
        ({"monday": [{"from": "06:00", "to": "8pm"}]}, "not a 24-hour clock time"),
        ({"monday": [{"from": None, "to": "20:00"}]}, "null where a time belongs"),
        # The device has no way to say "tomorrow" - a wire entry is a day
        # mask plus a start and an end - so a window that ends before it
        # starts cannot mean what a user intends by it.
        ({"monday": [{"from": "22:00", "to": "06:00"}]}, "ends before it starts"),
        # Coinciding ends are an EMPTY window on a real door, so accepting one
        # writes an entry that never fires while the card reads "Active 24/7".
        ({"monday": [{"from": "09:00", "to": "09:00"}]}, "covers no time at all"),
        ({"monday": [{"from": "23:59", "to": "23:59"}]}, "and not at the end of the day either"),
    ],
)
async def test_update_refuses_a_malformed_payload(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    hass_ws_client: WebSocketGenerator,
    payload: dict[str, Any],
    why: str,
) -> None:
    """Every shape the card cannot produce is rejected by the schema.

    Regression for finding S1. This surface is reachable by any logged-in
    user, so an unvalidated payload reached the write path and raised a raw
    KeyError or TypeError - and "24:00", which the card itself used to
    synthesise (finding F1), reached `time(24, 0)` deep inside it.

    A rejection is asserted alongside `set_schedule` never being awaited:
    a partial write that then failed validation would leave the door holding
    half an edit.
    """
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": WS_SCHEDULE_UPDATE, "entity_id": INSIDE, "schedule": payload}
    )
    result = await client.receive_json()

    assert result["success"] is False, why
    assert result["error"]["code"] == ws_const.ERR_INVALID_FORMAT
    mock_door.set_schedule.assert_not_awaited()


@pytest.mark.parametrize(
    ("payload", "why"),
    [
        ({}, "clearing the schedule entirely"),
        ({"monday": []}, "clearing one day"),
        ({"monday": [{"from": "00:00", "to": "00:00"}]}, "midnight to midnight, a whole day"),
        ({"monday": [{"from": "22:00", "to": "00:00"}]}, "22:00 to the end of the day"),
        ({"monday": [{"from": "23:59", "to": "00:00"}]}, "the last minute of the day"),
        ({"monday": [{"from": "22:00", "to": "23:59"}]}, "the other end-of-day spelling"),
        ({"monday": [{"from": "06:00:00", "to": "20:00:00"}]}, "seconds, as HA writes them"),
        (
            {"monday": [{"from": "06:00", "to": "08:00"}, {"from": "17:00", "to": "20:00"}]},
            "two windows in one day",
        ),
    ],
)
async def test_update_accepts_every_payload_the_card_can_produce(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    hass_ws_client: WebSocketGenerator,
    payload: dict[str, Any],
    why: str,
) -> None:
    """The other side of the validation boundary.

    A schema tested only with bad input can be arbitrarily strict and still
    look correct. Each of these is a real schedule the card draws, and
    "00:00-00:00" in particular is the out-of-box state - rejecting it would
    make the first edit any new user makes fail (finding F1).
    """
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": WS_SCHEDULE_UPDATE, "entity_id": INSIDE, "schedule": payload}
    )
    result = await client.receive_json()

    assert result["success"] is True, why


async def test_update_requires_a_schedule(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """Omitting the payload entirely is a format error, not an empty save.

    Treating a missing key as `{}` would let a buggy caller silently wipe
    the user's whole schedule.
    """
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": WS_SCHEDULE_UPDATE, "entity_id": INSIDE})
    result = await client.receive_json()

    assert result["success"] is False
    assert result["error"]["code"] == ws_const.ERR_INVALID_FORMAT


async def test_updating_one_door_does_not_touch_the_other(
    hass: HomeAssistant,
    two_doors: tuple[MockConfigEntry, MagicMock, MockConfigEntry, MagicMock],
    hass_ws_client: WebSocketGenerator,
) -> None:
    """The entity_id decides which door is written (issue #9).

    The commands are registered once for all doors, so the only thing
    routing a save to the right device is the registry lookup in `_resolve`.
    """
    _, first_door, _, second_door = two_doors

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": WS_SCHEDULE_UPDATE,
            "entity_id": INSIDE,
            "schedule": {"monday": [{"from": "06:00", "to": "20:00"}]},
        }
    )
    result = await client.receive_json()

    assert result["success"] is True
    first_door.set_schedule.assert_awaited()
    second_door.set_schedule.assert_not_awaited()


async def test_registering_the_api_twice_does_not_raise(
    hass: HomeAssistant,
    two_doors: tuple[MockConfigEntry, MagicMock, MockConfigEntry, MagicMock],
    hass_ws_client: WebSocketGenerator,
) -> None:
    """A second door must not re-register the global commands.

    `async_register_command` raises on a duplicate name, so without the
    once-per-run guard the SECOND door a user adds would fail to set up -
    with an error naming the WebSocket API, which has nothing obviously to
    do with adding a door.
    """
    first_entry, _, second_entry, _ = two_doors
    # Both entries LOADED is the assertion: the guard's absence made the
    # second one fail setup outright.
    assert first_entry.state is ConfigEntryState.LOADED
    assert second_entry.state is ConfigEntryState.LOADED

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": WS_SCHEDULE_LIST})
    result = await client.receive_json()

    assert result["success"] is True
