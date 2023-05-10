from __future__ import annotations

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry, SOURCE_IMPORT
from homeassistant.components.button import ButtonEntity
from .client import PowerPetDoorClient

from .const import (
    DOMAIN,
    CONF_HOST,
    CONF_PORT,
    CONF_NAME,
    COMMAND,
    DOOR_STATE_IDLE,
    DOOR_STATE_CLOSED,
    DOOR_STATE_KEEPUP,
    DOOR_STATE_HOLDING,
    CMD_OPEN,
    CMD_CLOSE,
    FIELD_POWER,
)

import logging

_LOGGER = logging.getLogger(__name__)

class PetDoorButton(ButtonEntity):
    _attr_should_poll = False
    last_state = None
    power = True

    def __init__(self,
                 client: PowerPetDoorClient,
                 name: str,
                 device: DeviceInfo | None = None) -> None:
        self.client = client

        self._attr_name = name
        self._attr_device_info = device
        self._attr_unique_id = f"{client.host}:{client.port}-button"

        client.add_listener(name=self.unique_id, door_status_update=self.handle_state_update, sensor_update={FIELD_POWER: self.handle_power_update})

    @property
    def available(self) -> bool:
        return self.client.available and self.power

    def handle_state_update(self, state: str) -> None:
        self.last_state = state
        self.async_schedule_update_ha_state()

    @callback
    def handle_power_update(self, state: bool) -> None:
        self.power = state
        self.async_schedule_update_ha_state()

    @property
    def icon(self) -> str | None:
        return "mdi:dog-side"

    async def press(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        return self.client.run_coroutine_threadsafe(self.async_press(**kwargs)).result()

    async def async_press(self, **kwargs: Any) -> None:
        """Open the cover."""
        if self.last_state in (DOOR_STATE_IDLE, DOOR_STATE_CLOSED):
            self.client.send_message(COMMAND, CMD_OPEN)
        if self.last_state in (DOOR_STATE_KEEPUP, DOOR_STATE_HOLDING):
            self.client.send_message(COMMAND, CMD_CLOSE)

# Right now this can be an alias for the above
async def async_setup_entry(hass: HomeAssistant,
                            entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:

    host = entry.data.get(CONF_HOST)
    port = entry.data.get(CONF_PORT)
    name = entry.data.get(CONF_NAME)
    obj = hass.data[DOMAIN][f"{host}:{port}"]

    async_add_entities([
        PetDoorButton(client=obj["client"],
                      name=f"{name} - Cycle",
                      device=obj["device"]),
    ])