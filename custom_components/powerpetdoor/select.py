from __future__ import annotations

from datetime import datetime, timezone as dt_timezone
import logging

from homeassistant.core import HomeAssistant, callback
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, CoordinatorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.components.select import SelectEntity
from .client import PowerPetDoorClient

from .const import (
    DOMAIN,
    CONF_HOST,
    CONF_PORT,
    CONF_NAME,
    CONFIG,
    STATE_LAST_CHANGE,
    FIELD_POWER,
    FIELD_TZ,
    CMD_SET_TIMEZONE,
)
from .tz_utils import (
    get_available_timezones,
    get_posix_tz_string,
    find_iana_for_posix,
    HA_TIMEZONE_OPTION,
)

_LOGGER = logging.getLogger(__name__)


class PetDoorTimezone(CoordinatorEntity, SelectEntity):
    """Select entity for Power Pet Door timezone configuration."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:map-clock-outline"
    _attr_entity_registry_enabled_default = False

    def __init__(self,
                 hass: HomeAssistant,
                 client: PowerPetDoorClient,
                 name: str,
                 coordinator: DataUpdateCoordinator,
                 device: DeviceInfo | None = None) -> None:
        super().__init__(coordinator)
        self.hass = hass
        self.client = client

        self.last_change = None
        self.power = True
        self._current_posix: str | None = None
        # Track the IANA timezone we selected (to display consistently)
        self._selected_iana: str | None = None

        self._attr_name = name
        self._attr_device_info = device
        self._attr_unique_id = f"{client.host}:{client.port}-timezone"
        self._attr_options = get_available_timezones()

        client.add_listener(
            name=self.unique_id,
            timezone_update=self.handle_timezone_update,
            sensor_update={FIELD_POWER: self.handle_power_update}
        )

    @property
    def available(self) -> bool:
        return self.client.available and super().available and self.power

    @property
    def current_option(self) -> str | None:
        """Return the currently selected timezone."""
        if self._current_posix is None:
            # Try to get from coordinator data
            if self.coordinator.data and FIELD_TZ in self.coordinator.data:
                self._current_posix = self.coordinator.data[FIELD_TZ]

        if not self._current_posix:
            return None

        # 1. If we previously selected a specific IANA timezone, check if it still matches
        if self._selected_iana and self._selected_iana != HA_TIMEZONE_OPTION:
            selected_posix = get_posix_tz_string(self._selected_iana)
            if selected_posix == self._current_posix:
                return self._selected_iana

        # 2. Check if Home Assistant's timezone matches the device's POSIX
        #    (HA option is write-only, so display the actual HA timezone name)
        ha_tz = self.hass.config.time_zone
        ha_posix = get_posix_tz_string(ha_tz)
        if ha_posix == self._current_posix:
            return ha_tz

        # 3. Fall back to reverse lookup from cache
        iana_name = find_iana_for_posix(self._current_posix)
        if iana_name:
            return iana_name

        # If no match found, return the raw POSIX string
        # (this handles edge cases where device has a custom timezone)
        return self._current_posix

    @property
    def extra_state_attributes(self) -> dict | None:
        rv = {}
        if self._current_posix:
            rv["posix_tz"] = self._current_posix
        if self.last_change:
            rv[STATE_LAST_CHANGE] = self.last_change.isoformat()
        return rv

    @callback
    def _handle_coordinator_update(self) -> None:
        self.last_change = datetime.now(dt_timezone.utc)
        if self.coordinator.data and FIELD_TZ in self.coordinator.data:
            self._current_posix = self.coordinator.data[FIELD_TZ]
        super()._handle_coordinator_update()

    @callback
    def handle_timezone_update(self, posix_tz: str) -> None:
        """Handle timezone update from device."""
        if posix_tz != self._current_posix:
            self._current_posix = posix_tz
            self.last_change = datetime.now(dt_timezone.utc)
            self.async_write_ha_state()

    @callback
    def handle_power_update(self, state: bool) -> None:
        self.power = state
        if self.enabled:
            self.async_schedule_update_ha_state()

    async def async_select_option(self, option: str) -> None:
        """Change the selected timezone."""
        if option == HA_TIMEZONE_OPTION:
            # Use Home Assistant's configured timezone
            ha_tz = self.hass.config.time_zone
            posix_tz = get_posix_tz_string(ha_tz)
            if not posix_tz:
                _LOGGER.error("Could not get POSIX TZ for Home Assistant timezone: %s", ha_tz)
                return
            _LOGGER.info("Setting timezone to Home Assistant timezone: %s (%s)", ha_tz, posix_tz)
            # Remember we selected the HA option
            self._selected_iana = HA_TIMEZONE_OPTION
        else:
            # Convert IANA name to POSIX string (from pre-built cache)
            posix_tz = get_posix_tz_string(option)
            if not posix_tz:
                _LOGGER.error("Could not get POSIX TZ string for timezone: %s", option)
                return
            # Remember which IANA timezone was selected
            self._selected_iana = option

        # Send to device
        self.client.send_message(CONFIG, CMD_SET_TIMEZONE, **{FIELD_TZ: posix_tz})


async def async_setup_entry(hass: HomeAssistant,
                            entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    """Set up the Power Pet Door select entities."""

    host = entry.data.get(CONF_HOST)
    port = entry.data.get(CONF_PORT)
    name = entry.data.get(CONF_NAME)
    obj = hass.data[DOMAIN][f"{host}:{port}"]

    async_add_entities([
        PetDoorTimezone(
            hass=hass,
            client=obj["client"],
            name=f"{name} Timezone",
            coordinator=obj["settings"],
            device=obj["device"]
        ),
    ])
