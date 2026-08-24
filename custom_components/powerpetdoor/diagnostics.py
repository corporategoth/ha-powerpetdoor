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
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "door": coordinator.diagnostics(),
    }
