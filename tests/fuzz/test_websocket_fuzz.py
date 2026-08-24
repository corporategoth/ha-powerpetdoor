# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""Randomized traffic at the one surface that faces inward.

The `powerpetdoor/schedule/*` commands are reachable by any logged-in Home
Assistant user, and the Lovelace card is their only intended caller. A
browser extension, a stale card, a hand-written script or a bug in the card
can all send something else.

The property asserted everywhere below is the same one: the connection gets
a well-formed answer. Never a hang - the card awaits the promise and a
handler that raised before answering leaves it pending forever, so the card
sits on "Loading schedule..." until the page is reloaded.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from hypothesis import given
from hypothesis import strategies as st
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.powerpetdoor.const import (
    WS_SCHEDULE_GET,
    WS_SCHEDULE_UPDATE,
)

INSIDE = "binary_sensor.power_pet_door_inside_schedule"

#: Anything JSON can carry, nested a little. This is what actually arrives
#: over a WebSocket - not neatly-typed Python objects.
json_values = st.recursive(
    st.none()
    | st.booleans()
    | st.integers(min_value=-(2**31), max_value=2**31)
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text(max_size=24),
    lambda children: (
        st.lists(children, max_size=3) | st.dictionaries(st.text(max_size=8), children, max_size=3)
    ),
    max_leaves=6,
)


@given(payload=json_values)
async def test_an_arbitrary_schedule_payload_is_answered_not_dropped(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    payload: Any,
) -> None:
    """Every update, however malformed, gets exactly one reply.

    Success or a refusal - the test does not care which, because that is
    what the deterministic suite pins. What it cares about is that SOMETHING
    comes back and that it is the right message: a handler that raised
    before answering strands the card's promise, and the user sees a
    schedule editor that never finishes loading and never says why.
    """
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": WS_SCHEDULE_UPDATE, "entity_id": INSIDE, "schedule": payload}
    )
    result = await client.receive_json()

    assert result["type"] == "result"
    assert isinstance(result["success"], bool)
    if not result["success"]:
        # A refusal has to carry a code and a message, or the card's toast
        # renders as "undefined".
        assert result["error"]["code"]
        assert isinstance(result["error"]["message"], str)


@given(entity_id=st.text(max_size=40))
async def test_an_arbitrary_entity_id_is_answered_not_dropped(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    entity_id: str,
) -> None:
    """`get` resolves an arbitrary string without raising.

    The entity_id comes from the card's YAML config, so a user who typed it
    by hand - or kept it after renaming the entity - sends whatever they
    like. `_resolve` walks the entity registry with it, and an unhandled
    lookup failure there is an unexplained error in the frontend rather
    than a "not a Power Pet Door schedule entity" the user can act on.
    """
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": WS_SCHEDULE_GET, "entity_id": entity_id})
    result = await client.receive_json()

    assert result["type"] == "result"
    if result["success"]:
        # The only string that may succeed is a real schedule entity.
        assert result["result"]["entity_id"] == entity_id
        assert result["result"]["kind"] in ("inside", "outside")
    else:
        assert result["error"]["code"]


@given(
    day=st.text(max_size=10),
    start=st.text(max_size=10),
    end=st.text(max_size=10),
)
async def test_arbitrary_day_and_time_strings_never_reach_the_door_unchecked(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: Any,
    hass_ws_client: WebSocketGenerator,
    day: str,
    start: str,
    end: str,
) -> None:
    """Anything that validates must be a real day and two real times.

    The interesting half is the success branch: it asserts that whatever got
    through is something the door can actually be told, so the schema cannot
    quietly widen without this failing.
    """
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": WS_SCHEDULE_UPDATE,
            "entity_id": INSIDE,
            "schedule": {day: [{"from": start, "to": end}]},
        }
    )
    result = await client.receive_json()

    if result["success"]:
        assert day in (
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
        )
        for value in (start, end):
            hour, _, rest = value.partition(":")
            assert 0 <= int(hour) <= 23
            assert 0 <= int(rest.partition(":")[0]) <= 59
