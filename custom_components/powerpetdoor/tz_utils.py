"""Timezone utilities for Power Pet Door.

Provides functions to convert IANA timezone names to POSIX TZ strings
using the tzdata package's TZif files via Python's importlib.resources API.

IMPORTANT: All file I/O is done during async_init_timezone_cache() which
must be called from an executor. After initialization, all lookups are
from in-memory caches with no blocking I/O.
"""
from __future__ import annotations

import logging

_LOGGER = logging.getLogger(__name__)

# Special option to use Home Assistant's configured timezone
HA_TIMEZONE_OPTION = "Use Home Assistant timezone"

# Module-level caches - populated by async_init_timezone_cache()
_iana_timezones: list[str] | None = None
_iana_to_posix: dict[str, str] = {}
_posix_to_iana: dict[str, str] = {}
_cache_initialized: bool = False


def _extract_posix_from_tzif(iana_timezone: str) -> str | None:
    """Extract the POSIX TZ string from a timezone's TZif file.

    This function does blocking I/O and should only be called from an executor.
    """
    try:
        import importlib.resources

        parts = iana_timezone.split('/')

        package = 'tzdata.zoneinfo'
        if len(parts) > 1:
            package = f'tzdata.zoneinfo.{".".join(parts[:-1])}'
            resource_name = parts[-1]
        else:
            resource_name = parts[0]

        with importlib.resources.as_file(
            importlib.resources.files(package).joinpath(resource_name)
        ) as path:
            with open(path, 'rb') as f:
                content = f.read()

        if content[:4] != b'TZif':
            return None

        last_newline = content.rfind(b'\n')
        if last_newline > 0:
            second_last_newline = content.rfind(b'\n', 0, last_newline)
            if second_last_newline >= 0:
                posix_tz = content[second_last_newline + 1:last_newline].decode('ascii')
                if posix_tz:
                    return posix_tz

        return None

    except Exception:
        return None


def _build_timezone_caches() -> None:
    """Build all timezone caches. Blocking I/O - call from executor only."""
    global _iana_timezones, _iana_to_posix, _posix_to_iana, _cache_initialized

    from zoneinfo import available_timezones

    # Get all IANA timezone names
    all_tzs = sorted(available_timezones())
    _iana_timezones = [HA_TIMEZONE_OPTION] + all_tzs

    # Build IANA -> POSIX and POSIX -> IANA mappings
    for tz_name in all_tzs:
        posix = _extract_posix_from_tzif(tz_name)
        if posix:
            _iana_to_posix[tz_name] = posix
            # First match wins for reverse lookup
            if posix not in _posix_to_iana:
                _posix_to_iana[posix] = tz_name

    _cache_initialized = True
    _LOGGER.debug(
        "Timezone cache initialized: %d timezones, %d POSIX mappings",
        len(_iana_timezones),
        len(_iana_to_posix)
    )


async def async_init_timezone_cache(hass) -> None:
    """Initialize timezone caches in an executor (non-blocking).

    Must be called once during integration setup before using other functions.
    """
    if _cache_initialized:
        return

    await hass.async_add_executor_job(_build_timezone_caches)


def is_cache_initialized() -> bool:
    """Check if the timezone cache has been initialized."""
    return _cache_initialized


def get_available_timezones() -> list[str]:
    """Get sorted list of available IANA timezone names with HA option first.

    Returns empty list if cache not initialized.
    """
    if _iana_timezones is None:
        _LOGGER.warning("Timezone cache not initialized, returning empty list")
        return [HA_TIMEZONE_OPTION]
    return _iana_timezones


def get_posix_tz_string(iana_timezone: str) -> str | None:
    """Get POSIX TZ string for an IANA timezone name.

    Returns None if not found or cache not initialized.
    """
    return _iana_to_posix.get(iana_timezone)


def find_iana_for_posix(posix_tz: str) -> str | None:
    """Find an IANA timezone name for a given POSIX TZ string.

    Returns None if not found or cache not initialized.
    """
    return _posix_to_iana.get(posix_tz)


def parse_posix_tz_string(posix_tz: str) -> dict | None:
    """Parse a POSIX TZ string into its components.

    Args:
        posix_tz: POSIX TZ string (e.g., 'EST5EDT,M3.2.0,M11.1.0')

    Returns:
        Dictionary with parsed components or None if parsing fails
    """
    if not posix_tz:
        return None

    result = {
        'raw': posix_tz,
        'std_abbrev': None,
        'std_offset': None,
        'dst_abbrev': None,
        'dst_offset': None,
        'dst_start': None,
        'dst_end': None,
    }

    try:
        if ',' in posix_tz:
            tz_part, rules = posix_tz.split(',', 1)
            rule_parts = rules.split(',')
            if len(rule_parts) >= 2:
                result['dst_start'] = rule_parts[0]
                result['dst_end'] = rule_parts[1]
        else:
            tz_part = posix_tz

        import re
        match = re.match(
            r'^([A-Za-z]+)(-?\d+(?::\d+(?::\d+)?)?)'
            r'(?:([A-Za-z]+)(-?\d+(?::\d+(?::\d+)?)?)?)?',
            tz_part
        )
        if match:
            result['std_abbrev'] = match.group(1)
            result['std_offset'] = match.group(2)
            result['dst_abbrev'] = match.group(3)
            result['dst_offset'] = match.group(4)

        return result

    except Exception as e:
        _LOGGER.debug("Error parsing POSIX TZ string %s: %s", posix_tz, e)
        return None
