# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""The config, reconfigure and options flows.

The flows are the only part of the integration a user drives before any
entity exists, so a failure here is a door that cannot be added at all. Each
test asserts the exact `type`, `step_id`/`reason` and error key, because
those strings are what `strings.json` renders - a flow that aborts for the
right reason under the wrong key shows the user an untranslated identifier.
"""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT, CONF_TIMEOUT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from powerpetdoor import CommandError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.powerpetdoor.config_flow import (
    async_validate_connection,
    options_schema,
)
from custom_components.powerpetdoor.const import (
    CONF_HOLD_MAX,
    CONF_HOLD_MIN,
    CONF_HOLD_STEP,
    CONF_KEEP_ALIVE,
    CONF_RECONNECT,
    CONF_REFRESH,
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_HOLD_MAX,
    DEFAULT_HOLD_MIN,
    DEFAULT_HOLD_STEP,
    DEFAULT_KEEP_ALIVE_TIMEOUT,
    DEFAULT_PORT,
    DEFAULT_RECONNECT_TIMEOUT,
    DEFAULT_REFRESH_TIMEOUT,
    DOMAIN,
)

from .conftest import TEST_HOST, TEST_PORT

NEW_HOST = "192.0.2.50"


@pytest.fixture
def probe_door() -> Generator[MagicMock]:
    """The throwaway `PowerPetDoor` the flow dials to test an address.

    Patched at `config_flow.PowerPetDoor`, not at the coordinator's: the
    flow builds its own short-lived door, and patching the wrong name would
    let the flow open a real socket that pytest-socket then blocks with an
    error nothing in the test explains.
    """
    door = MagicMock()
    door.connect = AsyncMock()
    door.disconnect = AsyncMock()
    # The flow does not stop at connect(): TCP alone proves only that
    # SOMETHING is listening. `refresh_status()` is the call that awaits a
    # real reply, so it is the one that decides whether an address holds a
    # door - and therefore the one a test makes fail to exercise an error
    # branch.
    door.refresh_status = AsyncMock()
    with patch("custom_components.powerpetdoor.config_flow.PowerPetDoor", return_value=door):
        yield door


@pytest.fixture
def bypass_setup() -> Generator[AsyncMock]:
    """Stop a created entry from actually setting up and dialling the door."""
    with patch("custom_components.powerpetdoor.async_setup_entry", return_value=True) as mock_setup:
        yield mock_setup


# ---------------------------------------------------------------------------
# async_validate_connection - the one helper both flows share
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (TimeoutError("no answer"), "timeout_connect"),
        (CommandError("garbage"), "invalid_response"),
        (ValueError("not a frame"), "invalid_response"),
        (OSError("no route to host"), "cannot_connect"),
        (ConnectionRefusedError("refused"), "cannot_connect"),
    ],
)
async def test_validate_connection_maps_each_failure_to_its_own_error_key(
    probe_door: MagicMock, raised: Exception, expected: str
) -> None:
    """Every failure mode gets its OWN message, not one generic one.

    These three keys exist in strings.json precisely so the user can tell
    "nothing is listening there" from "something is listening but it is not a
    pet door" - which is the difference between a wrong IP and a wrong port.
    Collapsing them would make the form useless for diagnosis.
    """
    probe_door.connect.side_effect = raised

    assert await async_validate_connection(TEST_HOST, TEST_PORT) == expected


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (TimeoutError, "timeout_connect"),
        (CommandError("garbage"), "invalid_response"),
        (ValueError("not a frame"), "invalid_response"),
        (OSError("no route to host"), "cannot_connect"),
    ],
)
async def test_validate_connection_maps_a_failure_from_the_status_probe_too(
    probe_door: MagicMock, raised: Exception, expected: str
) -> None:
    """The same table, failing at the call that actually proves it is a DOOR.

    Every other test here fails `connect()`, and `connect()` only establishes
    TCP - so `refresh_status()` could be deleted from the flow entirely and
    all of them still passed, at 100% coverage. That deletion is exactly the
    bug the call was added to fix: a typo'd octet landing on a NAS gets an
    entry, ~35 entities showing the library's constructor defaults, and
    `available` True, with no way for the user to tell it from a real door.

    This is the parametrisation that pins it, and the failure modes are the
    same because a door that answers TCP and then misbehaves must be
    diagnosed the same way as one that never answered.
    """
    probe_door.refresh_status.side_effect = raised

    assert await async_validate_connection(TEST_HOST, TEST_PORT) == expected


async def test_validate_connection_returns_none_when_the_door_answers(
    probe_door: MagicMock,
) -> None:
    """A reachable door produces no error key."""
    assert await async_validate_connection(TEST_HOST, TEST_PORT) is None
    # ...and it got there by ASKING, not merely by opening a socket.
    probe_door.refresh_status.assert_awaited_once()


async def test_validate_connection_always_releases_the_probe_socket(
    probe_door: MagicMock,
) -> None:
    """The probe disconnects even when the connect succeeded.

    A successful probe leaves a socket and a keepalive task behind, and the
    door accepts ONE client at a time - so leaking the probe means the real
    coordinator connection that follows is refused by the user's own door.
    """
    assert await async_validate_connection(TEST_HOST, TEST_PORT) is None
    probe_door.disconnect.assert_awaited_once()


async def test_validate_connection_releases_the_probe_socket_after_a_failure(
    probe_door: MagicMock,
) -> None:
    """...and after a failure, which is when a half-open socket is likeliest."""
    probe_door.connect.side_effect = TimeoutError

    assert await async_validate_connection(TEST_HOST, TEST_PORT) == "timeout_connect"
    probe_door.disconnect.assert_awaited_once()


# ---------------------------------------------------------------------------
# The user flow
# ---------------------------------------------------------------------------


async def test_user_flow_creates_an_entry_with_the_default_options(
    hass: HomeAssistant, probe_door: MagicMock, bypass_setup: AsyncMock
) -> None:
    """The happy path: a form, an address, an entry.

    The options are asserted in full. They are what the coordinator reads at
    construction time, so an entry created without them would fall back to
    library defaults and quietly ignore the constants in const.py.
    """
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_NAME: "Back Door", CONF_HOST: NEW_HOST, CONF_PORT: DEFAULT_PORT},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Back Door"
    assert result["data"] == {
        CONF_HOST: NEW_HOST,
        CONF_PORT: DEFAULT_PORT,
        CONF_NAME: "Back Door",
    }
    assert result["options"] == {
        CONF_TIMEOUT: DEFAULT_CONNECT_TIMEOUT,
        CONF_RECONNECT: DEFAULT_RECONNECT_TIMEOUT,
        CONF_KEEP_ALIVE: DEFAULT_KEEP_ALIVE_TIMEOUT,
        CONF_REFRESH: DEFAULT_REFRESH_TIMEOUT,
        CONF_HOLD_MIN: DEFAULT_HOLD_MIN,
        CONF_HOLD_MAX: DEFAULT_HOLD_MAX,
        CONF_HOLD_STEP: DEFAULT_HOLD_STEP,
    }
    assert result["result"].unique_id == f"{NEW_HOST}:{DEFAULT_PORT}"


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (TimeoutError, "timeout_connect"),
        (CommandError("garbage"), "invalid_response"),
        (OSError, "cannot_connect"),
    ],
)
async def test_user_flow_shows_the_error_and_lets_the_user_retry(
    hass: HomeAssistant, probe_door: MagicMock, raised: Exception, expected: str
) -> None:
    """A failed dial re-shows the form with the error, and does NOT abort.

    Aborting would make a typo unrecoverable without starting again, and -
    worse - the unique_id set before dialling would already be taken.
    """
    probe_door.connect.side_effect = raised

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_NAME: "Back Door", CONF_HOST: NEW_HOST, CONF_PORT: DEFAULT_PORT},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": expected}


async def test_user_flow_retry_succeeds_after_the_door_comes_back(
    hass: HomeAssistant, probe_door: MagicMock, bypass_setup: AsyncMock
) -> None:
    """The retry path actually works - the form is not a dead end.

    Asserting only that the error is shown would pass even if the flow were
    left in a state that could never create an entry, which is what setting
    the unique_id before dialling risks.
    """
    probe_door.connect.side_effect = OSError

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_NAME: "Back Door", CONF_HOST: NEW_HOST, CONF_PORT: DEFAULT_PORT},
    )
    assert result["errors"] == {"base": "cannot_connect"}

    probe_door.connect.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_NAME: "Back Door", CONF_HOST: NEW_HOST, CONF_PORT: DEFAULT_PORT},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_refuses_a_door_that_is_already_configured(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, probe_door: MagicMock
) -> None:
    """Adding the same host:port twice aborts (issue #9).

    Two entries for one door produced two coordinators, two connections and
    two sets of entities fighting over one device.
    """
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_NAME: "Duplicate", CONF_HOST: TEST_HOST, CONF_PORT: TEST_PORT},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_a_duplicate_is_rejected_before_the_door_is_dialled(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, probe_door: MagicMock
) -> None:
    """The duplicate check runs BEFORE connecting.

    The door accepts one client at a time and the existing entry already
    holds that slot, so probing here would either fail or - worse - succeed
    by evicting the working connection. This is why the ordering in
    `async_step_user` is not incidental.
    """
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_NAME: "Duplicate", CONF_HOST: TEST_HOST, CONF_PORT: TEST_PORT},
    )

    probe_door.connect.assert_not_awaited()


async def test_the_same_host_on_a_different_port_is_a_different_door(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    probe_door: MagicMock,
    bypass_setup: AsyncMock,
) -> None:
    """The unique_id is host:port, so the port side of it must decide too.

    The boundary that matters: TEST_PORT aborts (asserted above) and
    TEST_PORT + 1 must not. Testing only the abort would pass with a
    unique_id built from the host alone, which would make a second door
    behind one NAT address impossible to add.
    """
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_NAME: "Other", CONF_HOST: TEST_HOST, CONF_PORT: TEST_PORT + 1},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == f"{TEST_HOST}:{TEST_PORT + 1}"


async def test_the_user_form_offers_the_documented_defaults(
    hass: HomeAssistant, probe_door: MagicMock
) -> None:
    """The port field defaults to 3000, which is what the door listens on.

    Pinned by literal: a user who has not changed their door's port must be
    able to accept the form as-is, and README documents this number.
    """
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    defaults = {
        str(key): key.default()
        for key in result["data_schema"].schema
        if key.default is not vol.UNDEFINED
    }
    assert defaults[CONF_PORT] == 3000
    assert defaults[CONF_NAME] == "Power Pet Door"
    # CONF_HOST deliberately has NO default - there is nothing sensible to
    # guess, and a pre-filled host would be submitted unread.
    assert CONF_HOST not in defaults


# ---------------------------------------------------------------------------
# The reconfigure flow
# ---------------------------------------------------------------------------


async def test_reconfigure_moves_a_door_to_a_new_address(
    hass: HomeAssistant, setup_integration: MockConfigEntry, probe_door: MagicMock
) -> None:
    """A door that got a new DHCP lease can be pointed at it.

    Aborts with `reconfigure_successful` rather than creating an entry -
    that is Home Assistant's own convention for an update-in-place, and the
    key is in strings.json.
    """
    result = await setup_integration.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    # A DIFFERENT host - which is the whole point, and what the previous
    # version of this test failed to exercise: it submitted the unchanged
    # address, so it passed while reconfigure was incapable of changing one
    # (the flow aborted on any unique_id change, which an address change
    # necessarily is).
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_NAME: "Power Pet Door", CONF_HOST: NEW_HOST, CONF_PORT: TEST_PORT},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert setup_integration.data[CONF_HOST] == NEW_HOST
    # The unique_id must move with the address, or the entry keeps claiming
    # the old one and setting up the real door there would be refused.
    assert setup_integration.unique_id == f"{NEW_HOST}:{TEST_PORT}"


async def test_reconfigure_carries_every_entity_to_the_new_address(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    probe_door: MagicMock,
    entity_registry: er.EntityRegistry,
) -> None:
    """The entities keep their registry rows, so dashboards keep working.

    Every unique_id is `host:port` plus a suffix, so moving a door changes
    all of them at once. Without a migration Home Assistant files the
    reloaded entities as new ones: the count doubles, each new row takes a
    `_2` entity_id, and every card, automation and statistic still points at
    the original - which no longer exists. A DHCP lease is enough to cause
    it, and moving a door is the only thing this step is for.
    """
    before = er.async_entries_for_config_entry(entity_registry, setup_integration.entry_id)
    assert before, "nothing registered, so this test could not detect a duplicate"
    original_ids = {registry_entry.entity_id for registry_entry in before}

    result = await setup_integration.start_reconfigure_flow(hass)
    await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_NAME: "Power Pet Door", CONF_HOST: NEW_HOST, CONF_PORT: TEST_PORT},
    )
    await hass.async_block_till_done()

    after = er.async_entries_for_config_entry(entity_registry, setup_integration.entry_id)

    # Same rows, same entity_ids - not the same count with different rows.
    assert len(after) == len(before)
    assert {registry_entry.entity_id for registry_entry in after} == original_ids
    assert not [
        registry_entry for registry_entry in after if registry_entry.entity_id.endswith("_2")
    ]

    # And every unique_id now names the new address, or the next reload
    # would duplicate them after all.
    assert all(
        registry_entry.unique_id.startswith(f"{NEW_HOST}:{TEST_PORT}-") for registry_entry in after
    )


async def test_reconfigure_leaves_one_device_not_two(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    probe_door: MagicMock,
    device_registry: dr.DeviceRegistry,
) -> None:
    """The device is identified by address too, so it moves with the door."""
    result = await setup_integration.start_reconfigure_flow(hass)
    await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_NAME: "Power Pet Door", CONF_HOST: NEW_HOST, CONF_PORT: TEST_PORT},
    )
    await hass.async_block_till_done()

    devices = dr.async_entries_for_config_entry(device_registry, setup_integration.entry_id)
    assert len(devices) == 1
    assert devices[0].identifiers == {(DOMAIN, f"{NEW_HOST}:{TEST_PORT}")}


async def test_reconfigure_without_an_address_change_touches_no_registry(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    probe_door: MagicMock,
    entity_registry: er.EntityRegistry,
) -> None:
    """Renaming, or retrying after a failed connection, is not a move.

    The other side of the migration's guard: submitting the same address
    must leave the unique_ids exactly as they were rather than rewriting
    every row to the value it already had.
    """
    before = {
        registry_entry.entity_id: registry_entry.unique_id
        for registry_entry in er.async_entries_for_config_entry(
            entity_registry, setup_integration.entry_id
        )
    }

    result = await setup_integration.start_reconfigure_flow(hass)
    await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_NAME: "Renamed Door", CONF_HOST: TEST_HOST, CONF_PORT: TEST_PORT},
    )
    await hass.async_block_till_done()

    after = {
        registry_entry.entity_id: registry_entry.unique_id
        for registry_entry in er.async_entries_for_config_entry(
            entity_registry, setup_integration.entry_id
        )
    }
    assert after == before


async def test_reconfigure_works_on_an_entry_that_never_finished_setup(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    probe_door: MagicMock,
    mock_door: MagicMock,
) -> None:
    """The commonest reconfigure of all: fixing an address that never worked.

    An entry whose door was unreachable sits in SETUP_RETRY with no device
    and no entities, so there is nothing for the migration to move. It must
    still complete rather than fail on the missing device - this is the path
    a user takes after typing an octet wrong.

    `mock_door` as well as `probe_door`, because the two are different doors
    and this test needs both refused. `probe_door` is the throwaway the flow
    dials; the coordinator builds its own when the successful reconfigure
    RELOADS the entry, and that one is only unreachable if it is made so.
    Left real it opens an actual socket, which HA 2026.8.3 surfaces as a
    pytest-socket error attributed to a test that never mentions a network.
    """
    mock_door.connect.side_effect = OSError("no route to host")
    mock_config_entry.add_to_hass(hass)

    result = await mock_config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_NAME: "Power Pet Door", CONF_HOST: NEW_HOST, CONF_PORT: TEST_PORT},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data[CONF_HOST] == NEW_HOST
    # The premise, asserted rather than assumed: the new address is no more
    # reachable than the old one, so the entry is still retrying and still
    # has nothing in either registry for a later reconfigure to migrate.
    assert mock_config_entry.state is config_entries.ConfigEntryState.SETUP_RETRY


async def test_reconfigure_leaves_alone_a_unique_id_that_is_not_ours(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    probe_door: MagicMock,
    entity_registry: er.EntityRegistry,
) -> None:
    """The migration rewrites the address prefix, so it must first find one.

    Every entity this integration creates is `host:port-<key>`, but the
    rewrite slices that prefix off by length. An entry that did not carry it
    would be sliced at an arbitrary offset and silently corrupted, so
    anything that does not match is skipped rather than assumed.
    """
    foreign = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        "not-an-address-at-all",
        config_entry=setup_integration,
    )

    result = await setup_integration.start_reconfigure_flow(hass)
    await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_NAME: "Power Pet Door", CONF_HOST: NEW_HOST, CONF_PORT: TEST_PORT},
    )
    await hass.async_block_till_done()

    assert entity_registry.async_get(foreign.entity_id).unique_id == "not-an-address-at-all"


async def test_reconfigure_writes_the_new_name_and_address_to_the_entry(
    hass: HomeAssistant, setup_integration: MockConfigEntry, probe_door: MagicMock
) -> None:
    """The entry's data actually changes - the abort is not cosmetic."""
    result = await setup_integration.start_reconfigure_flow(hass)
    await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_NAME: "Renamed Door", CONF_HOST: NEW_HOST, CONF_PORT: TEST_PORT},
    )
    await hass.async_block_till_done()

    assert setup_integration.data[CONF_NAME] == "Renamed Door"
    assert setup_integration.data[CONF_HOST] == NEW_HOST


async def test_reconfigure_refuses_an_address_another_entry_already_owns(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    second_config_entry: MockConfigEntry,
    probe_door: MagicMock,
) -> None:
    """Moving a door onto a SECOND door's address aborts.

    This is the guard that has to survive fixing B11. Reconfigure must be
    able to change the address - that is its purpose - but not onto one
    another entry already holds, which would leave two entries fighting
    over one door. That is issue #9.

    Note what is NOT asserted: that the address is unchanged. The previous
    guard rejected every address change, which made reconfigure useless.
    """
    second_config_entry.add_to_hass(hass)

    result = await setup_integration.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Power Pet Door",
            CONF_HOST: second_config_entry.data[CONF_HOST],
            CONF_PORT: second_config_entry.data[CONF_PORT],
        },
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    # The original entry is untouched.
    assert setup_integration.data[CONF_HOST] == TEST_HOST


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (TimeoutError, "timeout_connect"),
        (CommandError("garbage"), "invalid_response"),
        (OSError, "cannot_connect"),
    ],
)
async def test_reconfigure_shows_the_error_rather_than_saving_a_dead_address(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    probe_door: MagicMock,
    raised: Exception,
    expected: str,
) -> None:
    """A door that does not answer at the new address leaves the entry alone.

    Saving it would take a working integration offline on a typo, with the
    old - correct - address already overwritten.
    """
    probe_door.connect.side_effect = raised

    result = await setup_integration.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_NAME: "Power Pet Door", CONF_HOST: TEST_HOST, CONF_PORT: TEST_PORT},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}
    assert setup_integration.data[CONF_HOST] == TEST_HOST


async def test_the_reconfigure_form_is_prefilled_with_the_current_address(
    hass: HomeAssistant, setup_integration: MockConfigEntry, probe_door: MagicMock
) -> None:
    """The form opens on the door's existing address, not on blanks.

    A user reconfiguring after an IP change edits one field; an empty form
    would make them retype the name and port from memory.
    """
    result = await setup_integration.start_reconfigure_flow(hass)

    suggested = {
        str(key): key.description["suggested_value"]
        for key in result["data_schema"].schema
        if key.description and "suggested_value" in key.description
    }
    assert suggested[CONF_HOST] == TEST_HOST
    assert suggested[CONF_PORT] == TEST_PORT


# ---------------------------------------------------------------------------
# The options flow
# ---------------------------------------------------------------------------


async def test_options_flow_saves_what_the_user_entered(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """Submitting the options form writes them to the entry."""
    result = await hass.config_entries.options.async_init(setup_integration.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    submitted = {
        CONF_TIMEOUT: 20.0,
        CONF_RECONNECT: 15.0,
        CONF_KEEP_ALIVE: 45.0,
        CONF_REFRESH: 600.0,
        CONF_HOLD_MIN: 1.0,
        CONF_HOLD_MAX: 30.0,
        CONF_HOLD_STEP: 0.5,
    }
    result = await hass.config_entries.options.async_configure(result["flow_id"], submitted)
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert setup_integration.options[CONF_HOLD_MAX] == 30.0
    assert setup_integration.options[CONF_TIMEOUT] == 20.0


async def test_options_flow_rejects_a_hold_range_whose_minimum_exceeds_its_maximum(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """Min > max is refused here, where the user can still fix it.

    Home Assistant renders a number entity whose min exceeds its max as a
    broken control with no explanation, so this has to be caught in the form
    rather than discovered on the dashboard.
    """
    result = await hass.config_entries.options.async_init(setup_integration.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_TIMEOUT: 5.0,
            CONF_RECONNECT: 5.0,
            CONF_KEEP_ALIVE: 30.0,
            CONF_REFRESH: 300.0,
            CONF_HOLD_MIN: 10.0,
            CONF_HOLD_MAX: 4.0,
            CONF_HOLD_STEP: 2.0,
        },
    )

    assert result["type"] is FlowResultType.FORM
    # Keyed to the field, not to "base": HA highlights the offending input.
    assert result["errors"] == {CONF_HOLD_MIN: "hold_range_inverted"}


async def test_a_hold_range_whose_minimum_equals_its_maximum_is_accepted(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """The boundary itself: min == max is a valid single-value control.

    The check is `>`, so this is the case that decides whether the operator
    is right. Testing only min > max would pass with `>=` too, which would
    reject a legitimate "always 4 seconds" configuration.
    """
    result = await hass.config_entries.options.async_init(setup_integration.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_TIMEOUT: 5.0,
            CONF_RECONNECT: 5.0,
            CONF_KEEP_ALIVE: 30.0,
            CONF_REFRESH: 300.0,
            CONF_HOLD_MIN: 4.0,
            CONF_HOLD_MAX: 4.0,
            CONF_HOLD_STEP: 2.0,
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_a_rejected_options_form_keeps_what_the_user_typed(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """The re-shown form carries the rejected values, not the saved ones.

    Resetting the form on error would discard the other seven fields the
    user had just filled in, to punish a mistake in one of them.
    """
    result = await hass.config_entries.options.async_init(setup_integration.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_TIMEOUT: 99.0,
            CONF_RECONNECT: 5.0,
            CONF_KEEP_ALIVE: 30.0,
            CONF_REFRESH: 300.0,
            CONF_HOLD_MIN: 10.0,
            CONF_HOLD_MAX: 4.0,
            CONF_HOLD_STEP: 2.0,
        },
    )

    defaults = {str(key): key.default() for key in result["data_schema"].schema}
    assert defaults[CONF_TIMEOUT] == 99.0
    assert defaults[CONF_HOLD_MIN] == 10.0


def test_the_options_schema_falls_back_to_defaults_for_an_entry_with_no_options() -> None:
    """An entry created before an option existed still renders a form.

    `options.get(key, DEFAULT)` per field rather than one blanket default:
    an entry migrated from an older version has SOME of these keys, and a
    missing one must not blank the fields beside it.
    """
    schema = options_schema({})

    defaults = {str(key): key.default() for key in schema.schema}
    assert defaults[CONF_TIMEOUT] == DEFAULT_CONNECT_TIMEOUT
    assert defaults[CONF_HOLD_MIN] == DEFAULT_HOLD_MIN
    assert defaults[CONF_HOLD_MAX] == DEFAULT_HOLD_MAX
    assert defaults[CONF_HOLD_STEP] == DEFAULT_HOLD_STEP


def test_the_options_schema_prefers_a_stored_value_over_the_default() -> None:
    """A stored option wins - the form shows what the door is actually using."""
    schema = options_schema({CONF_HOLD_MAX: 42.0})

    defaults = {str(key): key.default() for key in schema.schema}
    assert defaults[CONF_HOLD_MAX] == 42.0
    # ...and an unrelated field still falls back rather than vanishing.
    assert defaults[CONF_HOLD_MIN] == DEFAULT_HOLD_MIN
