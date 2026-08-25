# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""Carry entities forward from the releases before the rewrite.

Every entity is filed in the registry under `<host>:<port>-<key>`. Before
the rewrite that `key` was the door's own **protocol field name** -
`power_state`, `timersEnabled`, `sensorOnIndoorNotificationsEnabled` - one
per entity, taken straight off the wire. It is now the entity's translation
key, so that a name in `strings.json` and a registry entry cannot drift
apart.

That is a better scheme and it is also a rename of most of the identifiers
in the registry. Without this module Home Assistant sees the new keys as new
entities and files them alongside the old ones: the user gets a second Power
switch, a second Inside sensor, a second Outside sensor, and so on, with
every history, statistic, automation and dashboard reference still pointing
at the first - which no longer updates.

The old entry is the one kept, not the new one. It owns the history, and
renaming it leaves its `entity_id` alone, so dashboards and automations
that name it keep working across the upgrade.
"""

from __future__ import annotations

from typing import Final

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .coordinator import PowerPetDoorConfigEntry

#: Old registry key -> new one. Keyed on the suffix after `<host>:<port>-`.
#:
#: `button` is the one that is not a spelling change. The old integration
#: shipped a single button labelled "Cycle", but its press handler opened
#: the door when it read idle or closed and closed it when it read keepup or
#: holding - a toggle. It is mapped onto the button that does that now, not
#: onto the one that happens to share its old label.
LEGACY_UNIQUE_ID_KEYS: Final[dict[str, str]] = {
    "allowCmdLockout": "pet_proximity_keep_open",
    "button": "toggle",
    "doorOptions": "auto_retract",
    "holdOpenTime": "hold_open_time",
    "inside": "inside_sensor",
    "lowBatteryNotificationsEnabled": "notify_low_battery",
    "outside": "outside_sensor",
    "outsideSensorSafetyLock": "outside_safety_lock",
    "power_state": "power",
    "sensorOffIndoorNotificationsEnabled": "notify_inside_off",
    "sensorOffOutdoorNotificationsEnabled": "notify_outside_off",
    "sensorOnIndoorNotificationsEnabled": "notify_inside_on",
    "sensorOnOutdoorNotificationsEnabled": "notify_outside_on",
    "sensorTriggerVoltage": "sensor_trigger_voltage",
    "sleepSensorTriggerVoltage": "sleep_sensor_trigger_voltage",
    "timersEnabled": "auto",
    "totalAutoRetracts": "total_auto_retracts",
    "totalOpenCycles": "total_open_cycles",
}

#: Keys with no successor to rename to. The schedules were `schedule.*`
#: entities produced by monkeypatching Home Assistant's own `schedule`
#: integration at runtime; that patch is gone, so nothing will ever set
#: their state again. Their replacements are `binary_sensor` entities, and a
#: registry entry cannot change domain, so these cannot be renamed onto them
#: - only removed, or left showing `unavailable` forever.
LEGACY_DEAD_UNIQUE_ID_KEYS: Final[frozenset[str]] = frozenset(
    {"schedule-inside", "schedule-outside"}
)


@callback
def async_migrate_legacy_unique_ids(hass: HomeAssistant, entry: PowerPetDoorConfigEntry) -> None:
    """Rename pre-rewrite registry entries, and drop the ones with no successor.

    Must run before the platforms are forwarded. Each platform claims its
    `unique_id` as it adds entities, so a key renamed afterwards would have
    already lost the race to a freshly created duplicate.
    """
    registry = er.async_get(hass)
    prefix = f"{entry.runtime_data.device_identifier}-"

    entries = er.async_entries_for_config_entry(registry, entry.entry_id)
    # A registry entry is unique per (domain, platform, unique_id), so the
    # domain has to be part of the key here too - `binary_sensor` and
    # `switch` may both legitimately hold one.
    by_identity = {(item.domain, item.unique_id): item for item in entries}

    for item in entries:
        if not item.unique_id.startswith(prefix):
            continue
        key = item.unique_id[len(prefix) :]

        if key in LEGACY_DEAD_UNIQUE_ID_KEYS:
            registry.async_remove(item.entity_id)
            continue

        new_key = LEGACY_UNIQUE_ID_KEYS.get(key)
        if new_key is None:
            continue

        target = f"{prefix}{new_key}"
        # An upgrade that already ran once has BOTH: the old entity with the
        # history and a new empty one holding the identifier it needs. The
        # new one is discarded, because the only thing it owns is the name.
        clash = by_identity.get((item.domain, target))
        if clash is not None:
            registry.async_remove(clash.entity_id)

        registry.async_update_entity(item.entity_id, new_unique_id=target)
