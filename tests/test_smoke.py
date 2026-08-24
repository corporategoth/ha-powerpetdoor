# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""Smoke tests: the integration loads, and its entities reach the door.

Deliberately thin. This is not the test suite - it is the proof that the
rewrite runs at all, so that the exhaustive suite (edge cases, negatives,
fuzz, per-platform behaviour) has working ground to build on. See the
test-fanatic brief in .claude/analysis/PLAN.md.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from powerpetdoor import CommandError, Schedule, ScheduleTime
from pytest_homeassistant_custom_component.common import MockConfigEntry
from syrupy.assertion import SnapshotAssertion

from custom_components.powerpetdoor.const import DOMAIN

from .conftest import TEST_HOST, TEST_PORT


async def test_entry_sets_up_and_unloads(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """The entry loads, connects once, and unloads cleanly."""
    assert setup_integration.state is ConfigEntryState.LOADED
    mock_door.connect.assert_awaited_once()

    assert await hass.config_entries.async_unload(setup_integration.entry_id)
    await hass.async_block_till_done()

    assert setup_integration.state is ConfigEntryState.NOT_LOADED
    # The socket must actually be released, or a reload leaks a connection
    # per attempt.
    mock_door.disconnect.assert_awaited()


async def test_unreachable_door_retries_rather_than_failing(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_door: MagicMock
) -> None:
    """An unreachable door leaves the entry retrying, not errored.

    Platinum's test-before-setup. SETUP_RETRY (not SETUP_ERROR) is the
    assertion that matters: a door that is briefly unplugged must come back
    on its own without the user touching anything.
    """
    mock_door.connect.side_effect = OSError("no route to host")
    mock_config_entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_one_device_with_every_platform_represented(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Exactly one device, carrying entities from every platform."""
    device = device_registry.async_get_device(identifiers={(DOMAIN, f"{TEST_HOST}:{TEST_PORT}")})
    assert device is not None
    assert device.manufacturer == "High Tech Pet"

    entries = er.async_entries_for_config_entry(entity_registry, setup_integration.entry_id)
    assert entries, "no entities were created"

    # Every platform listed in __init__.PLATFORMS must actually produce at
    # least one entity; a platform that silently creates none is the kind of
    # thing that survives a green suite forever.
    produced = {entry.domain for entry in entries}
    assert produced == {platform.value for platform in Platform} & produced
    for platform in (
        Platform.BINARY_SENSOR,
        Platform.BUTTON,
        Platform.COVER,
        Platform.NUMBER,
        Platform.SELECT,
        Platform.SENSOR,
        Platform.SWITCH,
    ):
        assert platform.value in produced, f"{platform.value} produced no entities"


async def test_every_entity_has_a_unique_id_and_a_translation_key(
    setup_integration: MockConfigEntry, entity_registry: er.EntityRegistry
) -> None:
    """unique_ids are unique and prefixed; every entity is translatable."""
    entries = er.async_entries_for_config_entry(entity_registry, setup_integration.entry_id)

    unique_ids = [entry.unique_id for entry in entries]
    assert len(unique_ids) == len(set(unique_ids)), "duplicate unique_id"
    assert all(uid.startswith(f"{TEST_HOST}:{TEST_PORT}-") for uid in unique_ids)

    # has_entity_name + translation_key is the platinum requirement, and the
    # thing that makes strings.json the single source of user-facing text.
    assert all(entry.translation_key for entry in entries), "an entity has no translation_key"


@pytest.mark.parametrize(
    ("entity_id", "service", "method"),
    [
        ("switch.power_pet_door_power", "turn_off", "set_power"),
        ("switch.power_pet_door_inside_sensor", "turn_on", "set_inside_sensor"),
        ("button.power_pet_door_open", "press", "open"),
        ("button.power_pet_door_open_and_auto_close", "press", "cycle"),
    ],
)
async def test_commands_reach_the_door(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    entity_id: str,
    service: str,
    method: str,
) -> None:
    """Acting on an entity calls the matching door method.

    Includes the two buttons whose mapping is easy to get wrong: Open must
    hold the door open (`open`), and the auto-close button must be the timed
    open (`cycle`). They send different commands, so wiring both to one of
    them would silently lose a capability.
    """
    domain = entity_id.split(".", maxsplit=1)[0]
    await hass.services.async_call(domain, service, {"entity_id": entity_id}, blocking=True)
    getattr(mock_door, method).assert_awaited()


async def test_cover_opens_by_holding(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """The cover's open must hold, or it would close itself unprompted.

    `open()` holds; `cycle()` is the timed open. A cover wired to `cycle()`
    would report open and then close itself with no command behind it.
    """
    await hass.services.async_call(
        "cover", "open_cover", {"entity_id": "cover.power_pet_door_door"}, blocking=True
    )
    mock_door.open.assert_awaited_once()
    mock_door.cycle.assert_not_awaited()


async def test_a_failed_command_is_reported_to_the_user(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """A door that refuses a command raises, rather than failing silently."""
    mock_door.set_power.side_effect = CommandError("door said no")

    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            "switch",
            "turn_off",
            {"entity_id": "switch.power_pet_door_power"},
            blocking=True,
        )
    assert err.value.translation_key == "command_failed"


async def test_a_push_from_the_door_updates_entities(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """State pushed by the door reaches the entity without a poll.

    This is what makes the integration local_push rather than local_polling.
    """
    assert hass.states.get("switch.power_pet_door_inside_sensor").state == "on"

    mock_door.inside_sensor = False
    for callback in mock_door._callbacks["on_settings_change"]:
        callback({})
    await hass.async_block_till_done()

    assert hass.states.get("switch.power_pet_door_inside_sensor").state == "off"


async def test_disconnection_marks_entities_unavailable(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """Losing the door makes entities unavailable - except connectivity."""
    mock_door.connected = False
    for callback in mock_door._callbacks["on_disconnect"]:
        callback()
    await hass.async_block_till_done()

    assert hass.states.get("switch.power_pet_door_power").state == "unavailable"
    # The one entity whose entire job is to report - and undo - the outage
    # must survive it. An unavailable connection switch would say nothing
    # and offer no way back.
    assert hass.states.get("switch.power_pet_door_connection").state == "off"


async def test_a_powered_entity_goes_unavailable_when_the_door_drops_off(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """The OTHER availability class, which nothing exercised.

    `PowerPetDoorPoweredEntity.available` is
    `super().available and door.power` - two conditions, and every existing
    disconnect test used an entity of the plain class instead. So the pair was
    never run as "disconnected but powered", `super().available` could be
    dropped entirely, and the whole suite stayed green. That is CLAUDE.md test
    rule 9 exactly: `A and B` is one branch point with two destinations, and
    100% branch coverage is reached without ever running `A and not B`.

    Nine entities inherit it - the cover, both schedule sensors, four buttons
    and two switches - and every one of them would have kept showing a stale
    state for a door that had gone off the network, which is precisely when a
    user needs to be told.

    `door.power` is left TRUE on purpose: that is what isolates the
    connectivity half of the condition.
    """
    assert mock_door.power is True
    # A concrete state, not merely "not unavailable": an entity reporting
    # `unknown` is exactly as broken to a user, and the old assertion
    # passed for both.
    assert hass.states.get("cover.power_pet_door_door").state == "closed"

    mock_door.connected = False
    for callback in mock_door._callbacks["on_disconnect"]:
        callback()
    await hass.async_block_till_done()

    for entity_id in (
        "cover.power_pet_door_door",
        "binary_sensor.power_pet_door_inside_schedule",
        "button.power_pet_door_open",
        "switch.power_pet_door_inside_sensor",
    ):
        assert hass.states.get(entity_id).state == "unavailable", entity_id


async def test_a_powered_entity_goes_unavailable_when_the_motor_is_off(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """The other half of the same condition, so neither can be dropped.

    Connected, but the door's motor is powered down: the flap cannot move and
    a cover position would be a fiction. The power switch itself must stay
    available or there is no way to turn it back on - that one is deliberately
    NOT a powered entity.
    """
    mock_door.power = False
    for callback in mock_door._callbacks["on_settings_change"]:
        callback({})
    await hass.async_block_till_done()

    assert hass.states.get("cover.power_pet_door_door").state == "unavailable"
    assert hass.states.get("switch.power_pet_door_power").state == "off"


async def test_disabling_an_entity_cannot_break_the_connection(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_door: MagicMock,
    entity_registry: er.EntityRegistry,
) -> None:
    """Regression test for issue #18.

    Users disabled the latency sensor and the whole integration went
    unavailable, because an entity's `async_added_to_hass` owned
    `client.start()`. The connection now belongs to the coordinator and is
    established during entry setup, so no entity can be load-bearing.

    Asserted by disabling EVERY entity and checking the door is still
    connected - which is exactly the state the reporters ended up in.
    """
    for entry in er.async_entries_for_config_entry(entity_registry, setup_integration.entry_id):
        entity_registry.async_update_entity(
            entry.entity_id, disabled_by=er.RegistryEntryDisabler.USER
        )
    await hass.async_block_till_done()

    mock_door.disconnect.assert_not_awaited()
    assert mock_door.connected is True


async def test_the_connection_switch_frees_the_door_for_the_phone_app(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """Turning the connection off disconnects and stops reconnecting.

    The door accepts one client at a time, so this is how a user hands it
    back to the manufacturer's app without stopping Home Assistant.
    """
    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": "switch.power_pet_door_connection"},
        blocking=True,
    )
    mock_door.disconnect.assert_awaited()

    await hass.services.async_call(
        "switch",
        "turn_on",
        {"entity_id": "switch.power_pet_door_connection"},
        blocking=True,
    )
    # Once at setup, once here.
    assert mock_door.connect.await_count == 2


async def test_an_automation_can_set_a_schedule(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """The set_schedule action reaches the door (PR #19).

    The Lovelace card edits schedules over the WebSocket API, which only a
    browser can call. Without this action an automation could not do what
    the UI can - so a user could not switch to a winter schedule on a date.
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
    mock_door.set_schedule.assert_awaited()


async def test_the_schedule_summary_is_readable(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """schedule_entries renders windows as text a human can read (PR #19)."""
    # Monday, Wednesday, Friday 06:00-20:00, inside only. days_of_week is
    # indexed from SUNDAY, so this is [Sun, Mon, Tue, Wed, Thu, Fri, Sat].
    mock_door.schedules = [
        Schedule(
            index=0,
            enabled=True,
            days_of_week=[False, True, False, True, False, True, False],
            inside=True,
            outside=False,
            start=ScheduleTime(6, 0),
            end=ScheduleTime(20, 0),
        )
    ]
    for callback in mock_door._callbacks["on_schedule_change"]:
        callback([])
    await hass.async_block_till_done()

    state = hass.states.get("binary_sensor.power_pet_door_inside_schedule")
    assert state.attributes["schedule_entries"] == ["Mon, Wed, Fri: 06:00-20:00"]
    assert state.attributes["schedule_count"] == 3


#: The registry fields this integration actually DECIDES. An allow-list, not
#: a deny-list, and that distinction is load-bearing: a `RegistryEntry`
#: carries Home Assistant's own bookkeeping, and which fields exist changes
#: across the supported range. Measured on the CI matrix, three versions
#: disagree three different ways - 2026.8.3 adds `compat_aliases` and
#: `original_name_unprefixed`, 2026.2.3 has `object_id_base`, and 2025.4.0
#: lacks `suggested_object_id`.
#:
#: Snapshotting the whole entry therefore pins the shape of Home Assistant
#: rather than the shape of this integration: it passed on whichever version
#: happened to generate it and failed everywhere else, with a diff that said
#: nothing about the code. Excluding the offending field one at a time is
#: whack-a-mole; naming what we own is stable by construction.
#:
#: Everything a user's dashboard actually sees is here - the entity id and
#: unique id, the name and translation key, device class, category, icon,
#: unit, capabilities and supported features.
#:
#: `options` is deliberately NOT here even though it looks like ours: nothing
#: in this integration writes it, and Home Assistant fills it in with things
#: like `suggested_display_precision`, which 2025.4.0 does not have.
_SNAPSHOT_FIELDS = (
    "entity_id",
    "unique_id",
    "domain",
    "platform",
    "has_entity_name",
    "name",
    "original_name",
    "translation_key",
    "device_class",
    "original_device_class",
    "entity_category",
    "icon",
    "original_icon",
    "capabilities",
    "unit_of_measurement",
    "supported_features",
    "disabled_by",
    "hidden_by",
)


@pytest.mark.parametrize(
    "platform",
    [
        Platform.BINARY_SENSOR,
        Platform.BUTTON,
        Platform.COVER,
        Platform.NUMBER,
        Platform.SELECT,
        Platform.SENSOR,
        Platform.SWITCH,
    ],
)
@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_the_entity_surface_matches_its_snapshot(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_door: MagicMock,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
    platform: Platform,
) -> None:
    """Pin every entity, attribute and registry field, one platform at a time.

    `snapshot_platform` is Home Assistant core's own idiom for this, and it
    catches the whole class of change the hand-written assertions above
    cannot: a device class quietly changing, an entity becoming enabled by
    default, a unit or an icon moving, an entity disappearing. Reviewing the
    diff in tests/snapshots/ is how a reviewer sees what a change actually
    did to the user's dashboard.

    Parametrized with PLATFORMS patched to one entry because
    `snapshot_platform` asserts a single platform is loaded - it builds one
    snapshot per platform, and a mixed registry would make the diff
    unreadable. `entity_registry_enabled_by_default` forces the
    disabled-by-default entities on, so the snapshot covers the whole
    surface rather than only what a fresh install shows; whether each is
    disabled by default is itself recorded in the snapshot.
    """
    with patch("custom_components.powerpetdoor.PLATFORMS", [platform]):
        mock_config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    # Our own loop rather than `snapshot_platform`, so the entry is reduced to
    # `_SNAPSHOT_FIELDS` first - see the note there for why snapshotting a
    # whole RegistryEntry cannot work across the supported HA range. The
    # state is snapshotted whole, because that shape is stable.
    entries = er.async_entries_for_config_entry(entity_registry, mock_config_entry.entry_id)
    assert entries
    assert len({entry.domain for entry in entries}) == 1, "one platform at a time"

    for entry in entries:
        assert entry.disabled_by is None, "every entity must be enabled for the snapshot"
        surface = {field: getattr(entry, field) for field in _SNAPSHOT_FIELDS}
        assert surface == snapshot(name=f"{entry.entity_id}-entry")

        state = hass.states.get(entry.entity_id)
        assert state, f"no state for {entry.entity_id}"
        # The VALUE only, not the attributes. State attributes are as
        # version-variable as the registry entry was, in two ways at once:
        # 2026.8.3 changed the attribute KEYS from plain strings to StrEnum
        # members, so every key's repr changed, and it added derived
        # attributes such as the cover's `is_closed`. Neither is something
        # this integration decides.
        #
        # Nothing is lost. Everything this snapshot's docstring promises to
        # catch - a device class changing, a unit or icon moving, an entity
        # becoming enabled by default or disappearing - lives on the entry
        # above, and the live attribute values are asserted far more
        # precisely by the per-platform tests, one expected value at a time.
        assert state.state == snapshot(name=f"{entry.entity_id}-state")
