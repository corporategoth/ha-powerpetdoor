# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""Timezone helpers, wrapping the library's with one Home Assistant addition.

The door stores a POSIX TZ string. Everything about converting between that
and IANA names lives in `pypowerpetdoor.tz_utils`; the only thing added here
is the "use Home Assistant's timezone" option, which the library has no way
to know about.
"""

from __future__ import annotations

import logging

from powerpetdoor.tz_utils import (
    async_init_timezone_cache as _async_init_timezone_cache,
)
from powerpetdoor.tz_utils import (
    find_iana_for_posix,
    get_posix_tz_string,
    is_cache_initialized,
    parse_posix_tz_string,
)
from powerpetdoor.tz_utils import (
    get_available_timezones as _get_available_timezones,
)

_LOGGER = logging.getLogger(__name__)

#: Offered instead of an IANA name. Write-only: selecting it sets the door
#: to whatever Home Assistant is configured for at that moment, and the
#: entity then reports the resulting zone by its real name. It is not a
#: state the door can be in, so it never comes back as `current_option`.
HA_TIMEZONE_OPTION = "Use Home Assistant timezone"


async def async_init_timezone_cache() -> None:
    """Build the timezone cache without blocking the event loop.

    Enumerating the IANA database and deriving a POSIX string for each zone
    reads several hundred files, which must not happen on the event loop.
    The library already handles that - `async_init_timezone_cache` runs the
    scan with `asyncio.to_thread` and is safe to call concurrently - so this
    is a thin pass-through rather than a re-implementation with
    `hass.async_add_executor_job`. The previous version reached into the
    library's private `_build_timezone_caches` to do the same thing by hand.
    """
    if is_cache_initialized():
        return
    await _async_init_timezone_cache()


def get_available_timezones() -> list[str]:
    """Every IANA zone name, with the Home Assistant option first."""
    return [HA_TIMEZONE_OPTION, *_get_available_timezones()]


__all__ = [
    "HA_TIMEZONE_OPTION",
    "async_init_timezone_cache",
    "find_iana_for_posix",
    "get_available_timezones",
    "get_posix_tz_string",
    "is_cache_initialized",
    "parse_posix_tz_string",
]
