# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""Constants for the Power Pet Door integration.

Deliberately short. Everything about the *protocol* - commands, field names,
door states, priorities - lives in `pypowerpetdoor` and is reached through
the `PowerPetDoor` facade, never re-exported here. The previous version of
this file re-exported 90-odd library constants, which is what let entity
code drift into speaking the wire protocol directly.

What belongs here: Home Assistant configuration keys, defaults, and the
handful of names shared between platforms.
"""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "powerpetdoor"

# Configuration keys. CONF_NAME/CONF_HOST/CONF_PORT/CONF_TIMEOUT come from
# homeassistant.const and are imported where used rather than aliased here.
CONF_KEEP_ALIVE: Final = "keep_alive"
CONF_RECONNECT: Final = "reconnect"
CONF_REFRESH: Final = "refresh"
# NOTE: there is deliberately no CONF_UPDATE ("door position interval").
# It existed while the cover polled its own position; the door pushes status
# changes, so nothing reads it. It was still offered in the options form,
# where a user could set it, watch the entry reload, and see no effect and
# no error.
CONF_HOLD_MIN: Final = "hold_min"
CONF_HOLD_MAX: Final = "hold_max"
CONF_HOLD_STEP: Final = "hold_step"

# Defaults.
DEFAULT_NAME: Final = "Power Pet Door"
DEFAULT_PORT: Final = 3000
DEFAULT_CONNECT_TIMEOUT: Final = 10.0
DEFAULT_RECONNECT_TIMEOUT: Final = 5.0
DEFAULT_KEEP_ALIVE_TIMEOUT: Final = 30.0
DEFAULT_REFRESH_TIMEOUT: Final = 300.0

# The door's own app exposes 2-8s in 2s steps. The hardware accepts a much
# wider range, so these are the *defaults* for the number entity's bounds
# and the user can widen them in the options flow.
DEFAULT_HOLD_MIN: Final = 2.0
DEFAULT_HOLD_MAX: Final = 8.0
DEFAULT_HOLD_STEP: Final = 2.0

# Device identity, as shown in the device registry.
MANUFACTURER: Final = "High Tech Pet"
MODEL: Final = "WiFi Power Pet Door"

# Extra state attributes shared across platforms.
ATTR_SCHEDULE: Final = "schedule"
ATTR_SCHEDULE_ENTRIES: Final = "schedule_entries"
ATTR_SCHEDULE_COUNT: Final = "schedule_count"
ATTR_NEXT_EVENT: Final = "next_event"

# WebSocket command prefix. The Lovelace card in www/ is the other half of
# this contract; changing these breaks every dashboard using the card, so
# tests/frontend asserts the card sends exactly these.
WS_SCHEDULE_LIST: Final = f"{DOMAIN}/schedule/list"
WS_SCHEDULE_GET: Final = f"{DOMAIN}/schedule/get"
WS_SCHEDULE_UPDATE: Final = f"{DOMAIN}/schedule/update"

# The two schedule "kinds" the door supports. A schedule entry carries an
# inside flag and an outside flag independently, so one entry can drive
# both.
SCHEDULE_INSIDE: Final = "inside"
SCHEDULE_OUTSIDE: Final = "outside"

# Actions.
SERVICE_SET_SCHEDULE: Final = "set_schedule"
