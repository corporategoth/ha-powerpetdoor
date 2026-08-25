# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""Diagnostics support for the Power Pet Door."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from .coordinator import PowerPetDoorConfigEntry

# The door has no credentials - its protocol has no authentication at all -
# so the only thing worth redacting is where it lives on the user's network.
# Redacted anyway: diagnostics get pasted into public issue trackers, and a
# LAN address plus a port is more than a bug report needs.
TO_REDACT = {CONF_HOST}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: PowerPetDoorConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data

    # Two things the periodic refresh deliberately does not fetch, read here
    # instead. `door.refresh()` leaves both out on purpose - the clock is "a
    # diagnostic, and it goes stale the moment it arrives", the remote
    # pairing is "static pairing information, not live state" - and neither
    # earns a permanent entity: a clock that is up to a refresh interval
    # wrong is worse than none, and the pairing is a phone-app concern Home
    # Assistant can neither use nor change.
    #
    # A diagnostics download is exactly where they DO belong: it is asked
    # for, once, at the moment someone is debugging, so the cost is paid
    # only then and the values are accurate when read. The door clock is the
    # one way to see that a door will fire its schedules at the wrong time.
    await coordinator.async_refresh_diagnostic_data()

    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "door": coordinator.diagnostics(),
    }
