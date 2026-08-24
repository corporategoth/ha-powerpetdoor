# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""Tests for the timezone helpers.

`async_init_timezone_cache` guards a several-hundred-file scan behind
`is_cache_initialized()`, and that flag is process-global inside the
library. Which arm of the guard a test happens to take therefore depends on
what else has already run in the same process - under `pytest-xdist` that
means which worker the test landed on, which differs between a developer's
machine and a CI runner with a different core count.

That is exactly how it went wrong: the suite reached 100% locally while all
four CI cells missed the build arm, because there the cache was always
already warm by the time anything reached it. Both arms are pinned here by
controlling the flag directly, so neither depends on ordering.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from custom_components.powerpetdoor.tz_utils import (
    HA_TIMEZONE_OPTION,
    async_init_timezone_cache,
    get_available_timezones,
)


async def test_the_cache_is_built_when_it_has_not_been_built_yet() -> None:
    """The whole point of the call: a cold cache gets filled."""
    with (
        patch("custom_components.powerpetdoor.tz_utils.is_cache_initialized", return_value=False),
        patch(
            "custom_components.powerpetdoor.tz_utils._async_init_timezone_cache",
            new_callable=AsyncMock,
        ) as build,
    ):
        await async_init_timezone_cache()

    build.assert_awaited_once_with()


async def test_a_warm_cache_is_not_rebuilt() -> None:
    """The guard is the reason this is safe to call from every setup.

    Both the select platform's `async_setup_entry` and the tests' own
    fixtures call it, so on a door with several entries the scan would run
    once per entry - reading several hundred files each time, on the event
    loop's thread pool - if the flag were not consulted.
    """
    with (
        patch("custom_components.powerpetdoor.tz_utils.is_cache_initialized", return_value=True),
        patch(
            "custom_components.powerpetdoor.tz_utils._async_init_timezone_cache",
            new_callable=AsyncMock,
        ) as build,
    ):
        await async_init_timezone_cache()

    build.assert_not_awaited()


async def test_the_home_assistant_option_comes_first() -> None:
    """The card and the select both rely on the order, not just membership.

    It is offered as the first choice because it is the one a user wants
    without knowing their own IANA name; a real zone list follows it.
    """
    await async_init_timezone_cache()

    options = get_available_timezones()

    assert options[0] == HA_TIMEZONE_OPTION
    assert "America/New_York" in options
    assert HA_TIMEZONE_OPTION not in options[1:]
