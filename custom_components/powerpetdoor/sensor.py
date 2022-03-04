from __future__ import annotations

import logging
import json
import copy
from datetime import timedelta

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, CoordinatorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.components.sensor import SensorEntity
from .client import PowerPetDoorClient

from .const import (
    DOMAIN,
    CONF_HOST,
    CONF_PORT,
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
    _update_settings = None

    def __init__(self,
                 coordinator: DataUpdateCoordinator,
                 client: PowerPetDoorClient,
                 device: DeviceInfo | None = None,
                 update_settings_interval: float | None = None) -> None:
        super().__init__(coordinator)
        self.client = client
        self.update_settings_interval = update_settings_interval

        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect

        self._attr_name = coordinator.name
        self._attr_device_info = device
        self._attr_unique_id = f"{client.host}_{client.port}"
        self._attr_native_value = f"{client.host}_{client.port}"

        self.client.add_listener(name=self.unique_id,
                                 door_status_update=coordinator.async_set_updated_data,
                                 settings_update=self.handle_settings)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.client.start()

    async def async_will_remove_from_hass(self) -> None:
        self.client.stop()
        await super().async_will_remove_from_hass()

    @callback
    async def update_method(self) -> str:
        _LOGGER.debug("Requesting update of door status")
        future = self.send_message(CONFIG, CMD_GET_DOOR_STATUS, notify=True)
        return await future

    @property
    def available(self) -> bool:
        return self.client.available

    @property
    def extra_state_attributes(self) -> dict | None:
        rv = copy.deepcopy(self.settings)
        rv["host"] = self.client.host
        rv["port"] = self.client.port
        if self.coordinator.data:
            rv["status"] = self.coordinator.data
        return rv

    async def update_settings(self) -> None:
        await asyncio.sleep(update_settings_interval)
        if not self._update_settings.cancelled():
            self.client.send_message(CONFIG, CMD_GET_SETTINGS)
            self._update_settings = self.client.ensure_future(self.update_settings())

    async def handle_settings(self, settings: dict) -> None:
        if self._update_settings:
            self._update_settings.cancel()

        self.settings = settings

        _LOGGER.info("DOOR SETTINGS - {}".format(json.dumps(self.settings)))
        self.schedule_update_ha_state(self.coordinator.data is None)
        if self.update_settings_interval:
            self._update_settings = self.client.ensure_future(self.update_settings())

    def on_connect(self) -> None:
        self.client.send_message(CONFIG, CMD_GET_SETTINGS)

    def on_disconnect(self) -> None:
        if self._update_settings:
            self._update_settings.cancel()
            self_.update_settings = None

# Right now this can be an alias for the above
async def async_setup_entry(hass: HomeAssistant,
                            entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:

    host = entry.data.get(CONF_HOST)
    port = entry.data.get(CONF_PORT)
    name = entry.data.get(CONF_NAME)
    device_id = f"{host}:{port}"

    obj = hass.data[DOMAIN][device_id]

    async_add_entities([
        PetDoorCoordinator(coordinator=obj["coordinator"],
                           client=obj["config"],
                           device=obj["device"],
                           update_settings_interval=entry.data.get(CONF_REFRESH))
    ])
