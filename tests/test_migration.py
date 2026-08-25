# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""Carrying pre-rewrite entities across the unique_id rename.

Caught by installing on a real Home Assistant, not by this suite. The old
scheme filed each entity under the door's own protocol field name; the new
one uses the entity's translation key. Without a migration the user gets a
second Power switch, a second Inside sensor and so on, with every history,
statistic and dashboard reference still pointing at the first - which never
updates again.
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.powerpetdoor.const import DOMAIN
from custom_components.powerpetdoor.migration import (
    LEGACY_DEAD_UNIQUE_ID_KEYS,
    LEGACY_UNIQUE_ID_KEYS,
)

from .conftest import TEST_HOST, TEST_PORT

PREFIX = f"{TEST_HOST}:{TEST_PORT}"


def _register(
    entity_registry: er.EntityRegistry,
    entry: MockConfigEntry,
    domain: str,
    key: str,
    object_id: str,
) -> str:
    """File one entity under a legacy-style unique_id."""
    return entity_registry.async_get_or_create(
        domain,
        DOMAIN,
        f"{PREFIX}-{key}",
        config_entry=entry,
        suggested_object_id=object_id,
    ).entity_id


@pytest.mark.parametrize(("old_key", "new_key"), sorted(LEGACY_UNIQUE_ID_KEYS.items()))
async def test_every_legacy_key_is_renamed_in_place(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_door,
    entity_registry: er.EntityRegistry,
    old_key: str,
    new_key: str,
) -> None:
    """Each old key becomes its new one WITHOUT the entity_id moving.

    The entity_id is the half a user's dashboards and automations name, so
    renaming the registry key has to leave it alone. Parametrized one row
    per mapping so a broken entry names itself rather than hiding in a set
    comparison.
    """
    mock_config_entry.add_to_hass(hass)
    entity_id = _register(
        entity_registry, mock_config_entry, "switch", old_key, f"legacy_{old_key.lower()}"
    )

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    survivor = entity_registry.async_get(entity_id)
    assert survivor is not None, f"{entity_id} disappeared"
    assert survivor.unique_id == f"{PREFIX}-{new_key}"


async def test_an_upgrade_that_already_ran_keeps_the_entity_with_the_history(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_door,
    entity_registry: er.EntityRegistry,
) -> None:
    """The duplicate is discarded, not the original.

    This is the state a user is actually in after upgrading once without a
    migration: BOTH exist, the old one holding the history and the new one
    holding the identifier the platform now wants. Keeping the new one would
    make the migration a no-op that permanently strands the history.
    """
    mock_config_entry.add_to_hass(hass)
    old = _register(entity_registry, mock_config_entry, "switch", "power_state", "legacy_power")
    duplicate = _register(entity_registry, mock_config_entry, "switch", "power", "duplicate_power")
    assert old != duplicate

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert entity_registry.async_get(duplicate) is None, "the empty duplicate survived"
    survivor = entity_registry.async_get(old)
    assert survivor is not None, "the entity holding the history was removed"
    assert survivor.unique_id == f"{PREFIX}-power"

    # And it is LIVE, which is the half that pins the ordering. Migrating
    # after the platforms are forwarded reaches this same registry row, so
    # the assertions above pass either way - but the switch platform has by
    # then bound itself to the duplicate, and removing that leaves this row
    # with no entity behind it and no state until the next reload.
    assert hass.states.get(old) is not None, (
        "the surviving registry entry has no live entity - the migration ran "
        "after the platforms rather than before them"
    )


@pytest.mark.parametrize("dead_key", sorted(LEGACY_DEAD_UNIQUE_ID_KEYS))
async def test_the_schedule_entities_are_removed_rather_than_left_unavailable(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_door,
    entity_registry: er.EntityRegistry,
    dead_key: str,
) -> None:
    """They were `schedule.*`; their replacements are `binary_sensor`.

    A registry entry cannot change domain, so there is nothing to rename
    these onto. The monkeypatch that used to set their state is gone, so the
    only alternative to removing them is leaving two entities reading
    `unavailable` on the user's dashboard forever.
    """
    mock_config_entry.add_to_hass(hass)
    entity_id = _register(
        entity_registry, mock_config_entry, "schedule", dead_key, f"dead_{dead_key}"
    )

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert entity_registry.async_get(entity_id) is None


async def test_an_unrecognised_key_is_left_exactly_as_it_was(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_door,
    entity_registry: er.EntityRegistry,
) -> None:
    """The migration is a table, not a guess.

    Two negatives that matter: a key already in the new scheme must not be
    touched twice, and something filed under this config entry that the
    table does not name must be left alone rather than mangled by a
    best-effort rule.
    """
    mock_config_entry.add_to_hass(hass)
    already_new = _register(entity_registry, mock_config_entry, "sensor", "battery", "batt")
    foreign = _register(entity_registry, mock_config_entry, "sensor", "not-ours-at-all", "odd")

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert entity_registry.async_get(already_new).unique_id == f"{PREFIX}-battery"
    assert entity_registry.async_get(foreign).unique_id == f"{PREFIX}-not-ours-at-all"


async def test_the_old_cycle_button_becomes_the_toggle_not_the_cycle(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_door,
    entity_registry: er.EntityRegistry,
) -> None:
    """Mapped on behaviour, not on the label it happened to carry.

    The old integration's only button was labelled "Cycle", but its press
    handler opened the door when it read idle or closed and closed it when
    it read keepup or holding. That is `toggle`. `cycle` is the timed open,
    which the old button could never do, so inheriting the label would have
    silently changed what the user's existing button does.
    """
    mock_config_entry.add_to_hass(hass)
    entity_id = _register(entity_registry, mock_config_entry, "button", "button", "legacy_cycle")

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert entity_registry.async_get(entity_id).unique_id == f"{PREFIX}-toggle"
