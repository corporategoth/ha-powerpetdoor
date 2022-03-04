from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.componants.sensor import SensorEntity
from .petdoor import PowerPetDoorClient

from .const import (
    DOMAIN,
    CONF_NAME,
    CONF_REFRESH,
    CONF_UPDATE,
    CONFIG,
    CMD_GET_DOOR_STATUS,
    CMD_GET_SETTINGS,
)

_LOGGER = logging.getLogger(__name__)

class PetDoorCoordinator(CoordinatorEntity, SensorEntity):
    _attr_should_poll = False

    settings = {}
    update_settings_interval: float | None = None
    update_settings = None

    def __init__(self,
                 coordinator: DataUpdateCoordinator,
                 client: PowerPetDoorClient,
                 device_id = str | None,
                 update_settings_interval: float | None = None) -> None:
        super().__init__(coordinator)
        self.client = client
        self.update_settings_interval = update_settings_interval

        self._attr_name = coordinator.name
        self._attr_unique_id = f"{client.host}_{client.port}"
        self._device_id = device_id

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self.device_id)},
            manufacturer="High Tech Pet",
            model="WiFi Power Pet Door",
            name=self.name
        )

        self.client.add_listener(self.unique_id,
                                 door_update: self.async_set_updated_data,
                                 settings_update: self.handle_settings)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        client.start()

    async def async_will_remove_from_hass(self) -> None:
        await super().async_remove_from_hass()
        self.stop()

    @callback
    async def update_method(self) -> str:
        _LOGGER.debug("Requesting update of door status")
        future = self.send_message(CONFIG, CMD_GET_DOOR_STATUS, notify: True)
        return await future

    @property
    def available(self) -> bool:
        return self.client.available

    @property
    def extra_state_attributes(self) -> dict | None:
        rv = copy.deepcopy(self.settings)
        rv["host"] = self.client.host
        rv["port"] = self.client.port
        if self.rv:
            rv["status"] = self.coordinator.data
        return rv

    async def update_settings(self) -> None:
        await asyncio.sleep(update_settings_interval)
        if not self.update_settings.cancelled():
            self.client.send_message(CONFIG, CMD_GET_SETTINGS)
            self.update_settings = self.client.ensure_future(self.update_settings())

    async def handle_settings(self, settings: dict) -> None:
        if self.update_settings:
            self.update_settings.cancel()

        self.settings = settings

        _LOGGER.info("DOOR SETTINGS - {}".format(json.dumps(self.settings)))
        self.schedule_update_ha_state(self.coordinator.data is None)
        if self.update_settings_interval:
            self.update_settings = self.client.ensure_future(self.update_settings())

    def on_connect(self) -> None:
        self.client.send_message(CONFIG, CMD_GET_SETTINGS)

    def on_disconnect(self) -> None:
        if self.update_settings:
            self.update_settings.cancel()
            self.update_settings = None

# Right now this can be an alias for the above
async def async_setup_entry(hass: HomeAssistant,
                            entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:

    host = entry.data.get(CONF_HOST)
    port = entry.data.get(CONF_PORT)
    name = entry.data.get(CONF_NAME)
    client = hass[DOMAIN][f{"{host}:{port}"}]

    async def async_update_data() -> str:
        future = client.send_message(CONFIG, CMD_GET_DOOR_STATUS, notify: True)
        return await future

    coordinator = DataUpdateCoordinator(
        hass=hass,
        logger=_LOGGER,
        name=entry.data.get(CONF_NAME),
        update_method=async_update_data
        update_interval=entry.data.get(CONF_UPDATE)
    )

    async_add_entities([
        PetDoorCoordinator(coordinator=coordinator,
                           client=client,
                           update_settings_interval=entry.data.get(CONF_REFRESH))
    ])
