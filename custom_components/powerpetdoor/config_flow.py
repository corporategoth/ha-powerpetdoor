"""Adds config flow for power pet door integration."""
from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
import homeassistant.helpers.config_validation as cv

from homeassistant.const import (
    CONF_NAME,
    CONF_HOST,
    CONF_PORT,
    CONF_TIMEOUT,
)

from .const import (
    DOMAIN,
    CONF_REFRESH,
    CONF_KEEP_ALIVE,
    CONF_RECONNECT,
    CONF_HOLD,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_RECONNECT_TIMEOUT,
    DEFAULT_KEEP_ALIVE_TIMEOUT,
    DEFAULT_REFRESH_TIMEOUT,
    DEFAULT_HOLD,
)

DATA_SCHEMA = vol.Schema({
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Required(CONF_HOST): cv.string,
    vol.Optional(CONF_HOLD, default=DEFAULT_HOLD): cv.boolean,
})
DATA_SCHEMA_ADV = vol.Schema({
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Required(CONF_HOST): cv.string,
    vol.Optional(CONF_HOLD, default=DEFAULT_HOLD): cv.boolean,
    vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
    vol.Optional(CONF_TIMEOUT, default=DEFAULT_CONNECT_TIMEOUT): cv.time_period_seconds,
    vol.Optional(CONF_RECONNECT, default=DEFAULT_RECONNECT_TIMEOUT): cv.time_period_seconds,
    vol.Optional(CONF_KEEP_ALIVE, default=DEFAULT_KEEP_ALIVE_TIMEOUT): cv.time_period_seconds,
    vol.Optional(CONF_REFRESH, default=DEFAULT_REFRESH_TIMEOUT): cv.time_period_seconds,
    })

class PowerPetDoorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for power pet door integration."""

    VERSION = 1

    async def async_step_import(self, config: dict[str, Any]) -> FlowResult:
        """Import a configuration from config.yaml."""

        host = config.get(CONF_HOST)
        self._async_abort_entries_match({CONF_HOST: host})
        config[CONF_HOST] = host
        return await self.async_step_user(user_input=config)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""

        errors = {}
        if user_input is not None:
            host = user_input.get(CONF_HOST)
            name = user_input.get(CONF_NAME)

            await self.async_set_unique_id(host)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(title=name, data=user_input)

        if self.show_advanced_options is True:
            return self.async_show_form(step_id="user", data_schema=DATA_SCHEMA_ADV, errors)

        return self.async_show_form(step_id="user", data_schema=DATA_SCHEMA, errors)

class PowerPetDoorOptionsFlow(config_entries.OptionsFlow):
    """Handle a option config for power pet door integration."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.entry = entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""

        errors = {}
        if user_input is not None:
            return self.async_create_entry(title=name, data=user_input)

        if self.show_advanced_options is True:
            return self.async_show_form(step_id="user", data_schema=DATA_SCHEMA_ADV, errors)

        return self.async_show_form(step_id="user", data_schema=DATA_SCHEMA, errors)
