# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""Select entities for the Power Pet Door."""

from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from powerpetdoor import CommandError

from .const import DOMAIN
from .coordinator import PowerPetDoorConfigEntry, PowerPetDoorCoordinator
from .entity import PowerPetDoorEntity
from .tz_utils import (
    HA_TIMEZONE_OPTION,
    async_init_timezone_cache,
    find_iana_for_posix,
    get_available_timezones,
    get_posix_tz_string,
)

PARALLEL_UPDATES = 1

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowerPetDoorConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Power Pet Door selects."""
    # Built here rather than during entry setup: the timezone select is the
    # only consumer and is disabled by default, so a user who never enables
    # it never pays for the IANA scan. The entity reads the cache while
    # constructing its option list, so it has to be warm before that.
    await async_init_timezone_cache()
    async_add_entities([PowerPetDoorTimezone(entry.runtime_data)])


class PowerPetDoorTimezone(PowerPetDoorEntity, SelectEntity):
    """The door's timezone.

    The door stores a POSIX TZ string (`EST5EDT,M3.2.0,M11.1.0`), not an
    IANA name, and that mapping is many-to-one: every US Eastern zone
    produces the same POSIX string. So the selected IANA name is remembered
    locally and only re-derived when the door reports something that no
    longer matches it - otherwise picking "America/Toronto" would snap back
    to "America/New_York" on the next refresh.
    """

    entity_description = SelectEntityDescription(
        key="timezone",
        translation_key="timezone",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    )

    def __init__(self, coordinator: PowerPetDoorCoordinator) -> None:
        """Initialise the timezone select."""
        super().__init__(coordinator, self.entity_description.key)
        self._attr_options = get_available_timezones()
        self._selected: str | None = None

    @property
    def current_option(self) -> str | None:
        """The door's timezone as an IANA name where one can be found."""
        posix = self.coordinator.door.timezone
        if not posix:
            return None

        # 1. What the user picked, if the door still agrees with it.
        if self._selected and get_posix_tz_string(self._selected) == posix:
            return self._selected

        # 2. Home Assistant's own zone, if it matches. Reported by its real
        #    name rather than as the "use Home Assistant timezone" option,
        #    which is a write-only instruction and not a state.
        ha_zone = self.hass.config.time_zone
        if ha_zone and get_posix_tz_string(ha_zone) == posix:
            return ha_zone

        # 3. Any IANA name that produces this POSIX string.
        if (iana := find_iana_for_posix(posix)) is not None:
            return iana

        # 4. A custom or unrecognised POSIX string. Returned raw so the user
        #    can at least see what the door holds; it will not be one of
        #    `options`, which HA renders as an invalid selection - which is
        #    accurate, because it is.
        return posix

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Expose the raw POSIX string the door actually holds."""
        return {"posix_tz": self.coordinator.door.timezone}

    async def async_select_option(self, option: str) -> None:
        """Set the door's timezone."""
        if option == HA_TIMEZONE_OPTION:
            zone = self.hass.config.time_zone
            selected: str | None = None
        else:
            zone = option
            selected = option

        posix = get_posix_tz_string(zone) if zone else None
        if not posix:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_timezone",
                translation_placeholders={"timezone": zone or "unset"},
            )

        try:
            await self.coordinator.door.set_timezone(posix)
        except (CommandError, OSError, TimeoutError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err

        self._selected = selected
        self.coordinator.async_update_listeners()
