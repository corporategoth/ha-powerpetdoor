# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""Timezone utilities for Power Pet Door Home Assistant integration.

This module wraps the powerpetdoor library's timezone utilities and adds
Home Assistant-specific functionality like the "Use Home Assistant timezone" option.
"""
from __future__ import annotations

import logging

# Import all timezone utilities from the library
from powerpetdoor.tz_utils import (
    async_init_timezone_cache as _async_init_timezone_cache,
    is_cache_initialized,
    get_available_timezones as _get_available_timezones,
    get_posix_tz_string,
    find_iana_for_posix,
    parse_posix_tz_string,
)

_LOGGER = logging.getLogger(__name__)

# Special option to use Home Assistant's configured timezone
HA_TIMEZONE_OPTION = "Use Home Assistant timezone"


async def async_init_timezone_cache(hass) -> None:
    """Initialize timezone caches using Home Assistant's executor.

    This wraps the library function to use Home Assistant's executor
    for better integration with the HA event loop.

    Must be called once during integration setup before using other functions.
    """
    if is_cache_initialized():
        return

    # Use HA's executor for the blocking operation
    from powerpetdoor.tz_utils import _build_timezone_caches
    await hass.async_add_executor_job(_build_timezone_caches)


def get_available_timezones() -> list[str]:
    """Get sorted list of available IANA timezone names with HA option first.

    Returns list with "Use Home Assistant timezone" as first option,
    followed by all IANA timezone names.
    """
    timezones = _get_available_timezones()
    if not timezones:
        return [HA_TIMEZONE_OPTION]
    return [HA_TIMEZONE_OPTION] + timezones


# Re-export other functions as-is
__all__ = [
    "HA_TIMEZONE_OPTION",
    "async_init_timezone_cache",
    "is_cache_initialized",
    "get_available_timezones",
    "get_posix_tz_string",
    "find_iana_for_posix",
    "parse_posix_tz_string",
]
