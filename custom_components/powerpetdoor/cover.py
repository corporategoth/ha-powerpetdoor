from __future__ import annotations

from datetime import datetime, timezone

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, CoordinatorEntity
from homeassistant.config_entries import ConfigEntry, SOURCE_IMPORT
from homeassistant.components.cover import CoverEntity, CoverDeviceClass
from homeassistant.helpers import entity_platform
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
    SERVICE_OPEN,
    SERVICE_CLOSE,
    SERVICE_TOGGLE,
)

import logging

_LOGGER = logging.getLogger(__name__)

class PetDoor(CoordinatorEntity, CoverEntity):
    _attr_device_class = CoverDeviceClass.SHUTTER
    _attr_position = None

    last_change = None

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

        self._attr_name = name
        self._attr_device_info = device
        self._attr_unique_id = f"{client.host}:{client.port}-door"

        client.add_listener(name=self.unique_id, door_status_update=self.handle_state_update)

    async def update_method(self) -> str:
        _LOGGER.debug("Requesting update of door status")
        future = self.client.send_message(CONFIG, CMD_GET_DOOR_STATUS, notify=True)
        return await future

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        await self.coordinator.async_refresh()

    @callback
    async def async_update(self) -> None:
        _LOGGER.debug("Requesting update of door status")
        future = self.client.send_message(CONFIG, CMD_GET_DOOR_STATUS, notify=True)
        return await future

    @property
    def available(self) -> bool:
        return (self.client.available and super().available)

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
    def is_closed(self) -> bool | None:
        """Return True if entity is on."""
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

    async def open_cover(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        return self.client.run_coroutine_threadsafe(self.async_open_cover(**kwargs)).result()

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        self.client.send_message(COMMAND, CMD_OPEN_AND_HOLD)

    async def close_cover(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        return self.client.run_coroutine_threadsafe(self.async_close_cover(**kwargs)).result()

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        self.client.send_message(COMMAND, CMD_CLOSE)

    def toggle(self, **kwargs: Any) -> None:
        """Toggle the entity."""
        if self.is_closed:
            self.open_cover(**kwargs)
        else:
            self.close_cover(**kwargs)

    async def async_toggle(self, **kwargs: Any) -> None:
        """Toggle the entity."""
        if self.is_closed:
            await self.async_open_cover(**kwargs)
        else:
            await self.async_close_cover(**kwargs)

async def async_setup_platform(
        hass: HomeAssistant,
        config: ConfigType,
        async_add_devices: AddEntitiesCallback,
        discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the Power Pet Door sensor."""
    _LOGGER.warning(
        "Configuration of the Power Pet Door platform in YAML is deprecated and "
        "will be removed in Home Assistant 2022.6; Your existing configuration "
        "has been imported into the UI automatically and can be safely removed "
        "from your configuration.yaml file"
    )

    hass.async_create_task(
        hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_IMPORT},
            data=config,
        )
    )

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
                name=f"{name}",
                device=obj["device"],
                update_interval=entry.options.get(CONF_UPDATE, entry.data.get(CONF_UPDATE)))
    ])