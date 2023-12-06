from __future__ import annotations

from datetime import datetime, timezone, timedelta

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, CoordinatorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.components.cover import CoverEntity, CoverDeviceClass, SUPPORT_CLOSE, SUPPORT_OPEN
from .client import PowerPetDoorClient

from .const import (
    DOMAIN,
    CONF_HOST,
    CONF_PORT,
    CONF_NAME,
    CONF_UPDATE,
    COMMAND,
    CONFIG,
    DOOR_STATE_IDLE,
    DOOR_STATE_CLOSED,
    DOOR_STATE_HOLDING,
    DOOR_STATE_KEEPUP,
    DOOR_STATE_SLOWING,
    DOOR_STATE_RISING,
    DOOR_STATE_CLOSING_TOP_OPEN,
    DOOR_STATE_CLOSING_MID_OPEN,
    CMD_GET_DOOR_STATUS,
    CMD_OPEN_AND_HOLD,
    CMD_CLOSE,
    STATE_LAST_CHANGE,
    FIELD_DOOR_STATUS,
    FIELD_POWER,
)

import logging

_LOGGER = logging.getLogger(__name__)

class PetDoor(CoordinatorEntity, CoverEntity):
    _attr_device_class = CoverDeviceClass.SHUTTER
    _attr_supported_features = (SUPPORT_CLOSE | SUPPORT_OPEN)
    _attr_position = None

    def __init__(self,
                 hass: HomeAssistant,
                 client: PowerPetDoorClient,
                 name: str,
                 device: DeviceInfo | None = None,
                 update_interval: float | None = None) -> None:
        coordinator = DataUpdateCoordinator(
            hass=hass,
            logger=_LOGGER,
            name=name,
            update_method=self.update_method,
            update_interval=timedelta(seconds=update_interval) if update_interval else None)

        super().__init__(coordinator)
        self.client = client

        self.last_change = None
        self.power = True

        self._attr_name = name
        self._attr_device_info = device
        self._attr_unique_id = f"{client.host}:{client.port}-door"

        client.add_listener(name=self.unique_id,
                            door_status_update=self.handle_state_update,
                            sensor_update={FIELD_POWER: self.handle_power_update})
        self.client.add_handlers(name, on_connect=self.coordinator.async_request_refresh)

    async def update_method(self) -> str:
        _LOGGER.debug("Requesting update of door status")
        future = self.client.send_message(CONFIG, CMD_GET_DOOR_STATUS, notify=True)
        return await future

    @property
    def available(self) -> bool:
        return (self.client.available and super().available and self.power)

    @property
    def current_cover_position(self) -> int | None:
        if self.coordinator.data is None:
            return None
        elif self.coordinator.data in (DOOR_STATE_IDLE, DOOR_STATE_CLOSED):
            return 0
        elif self.coordinator.data in (DOOR_STATE_HOLDING, DOOR_STATE_KEEPUP):
            return 100
        elif self.coordinator.data in (DOOR_STATE_SLOWING, DOOR_STATE_CLOSING_TOP_OPEN):
            return 66
        elif self.coordinator.data in (DOOR_STATE_RISING, DOOR_STATE_CLOSING_MID_OPEN):
            return 33

    @property
    def is_opening(self) -> bool | None:
        """Return True if entity is on."""
        if self.coordinator.data is None:
            return None
        return (self.coordinator.data in (DOOR_STATE_RISING, DOOR_STATE_SLOWING))

    @property
    def is_closing(self) -> bool | None:
        """Return True if entity is on."""
        if self.coordinator.data is None:
            return None
        return (self.coordinator.data in (DOOR_STATE_CLOSING_TOP_OPEN, DOOR_STATE_CLOSING_MID_OPEN))

    @property
    def is_closed(self) -> bool | None:
        """Return True if entity is on."""
        if self.coordinator.data is None:
            return None
        return (self.coordinator.data in (DOOR_STATE_IDLE, DOOR_STATE_CLOSED))

    @property
    def extra_state_attributes(self) -> dict | None:
        rv = {}
        if self.coordinator.data:
            rv[FIELD_DOOR_STATUS] = self.coordinator.data
        if self.last_change:
            rv[STATE_LAST_CHANGE] = self.last_change.isoformat()
        return rv

    @callback
    def _handle_coordinator_update(self) -> None:
        self.last_change = datetime.now(timezone.utc)
        super()._handle_coordinator_update()

    @callback
    def handle_state_update(self, state: str) -> None:
        if state != self.coordinator.data:
            self.coordinator.async_set_updated_data(state)

    @callback
    def handle_power_update(self, state: bool) -> None:
        self.power = state
        self.async_schedule_update_ha_state()

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        self.client.send_message(COMMAND, CMD_OPEN_AND_HOLD)

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        self.client.send_message(COMMAND, CMD_CLOSE)

    async def async_toggle(self, **kwargs: Any) -> None:
        """Toggle the entity."""
        if self.is_closed:
            await self.async_open_cover(**kwargs)
        else:
            await self.async_close_cover(**kwargs)

# Right now this can be an alias for the above
async def async_setup_entry(hass: HomeAssistant,
                            entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:

    host = entry.data.get(CONF_HOST)
    port = entry.data.get(CONF_PORT)
    name = entry.data.get(CONF_NAME)
    obj = hass.data[DOMAIN][f"{host}:{port}"]

    async_add_entities([
        PetDoor(hass=hass,
                client=obj["client"],
                name=f"{name} Door",
                device=obj["device"],
                update_interval=entry.options.get(CONF_UPDATE))
    ])
