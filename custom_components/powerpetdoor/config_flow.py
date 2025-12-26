# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""Config flow for Power Pet Door integration."""
from __future__ import annotations

import logging
import asyncio
import json
import time
from typing import Any

import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    CONF_NAME,
    CONF_HOST,
    CONF_PORT,
    DEFAULT_PORT,
    FIELD_SUCCESS,
    PING,
    PONG,
)

from .schema import PP_SCHEMA, PP_SCHEMA_ADV, PP_OPT_SCHEMA, get_input_schema

_LOGGER = logging.getLogger(__name__)

async def validate_connection(host: str, port: int) -> str | None:
    error = None
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host=host, port=port), timeout=5.0)
        try:
            last_ping = str(round(time.time()*1000))
            writer.write('{{"{}": "{}", "dir": "p2d"}}'.format(PING, last_ping).encode("ascii"))
            await asyncio.wait_for(writer.drain(), timeout=5.0)

            try:
                data = await asyncio.wait_for(reader.readuntil(b'}'), timeout=5.0)
                pong = json.loads(data.decode('ascii'))
                if FIELD_SUCCESS not in pong:
                    error = "protocol_error"
                elif pong[FIELD_SUCCESS] != "true":
                    error = "ping_failed"
                elif "CMD" not in pong:
                    error = "protocol_error"
                elif pong["CMD"] != PONG:
                    error = "invalid_response"
                elif PONG not in pong:
                    error = "protocol_error"
                elif pong[PONG] != last_ping:
                    error = "bad_ping"
            except json.JSONDecodeError:
                error = "protocol_error"
            except asyncio.TimeoutError:
                error = "read_timed_out"
            except:
                error = "read_error"
        except asyncio.TimeoutError:
            error = "write_timed_out"
        except:
            error = "write_error"
        writer.close()
        await writer.wait_closed()
    except asyncio.TimeoutError:
        error = "connection_timed_out"
    except:
        error = "connection_failed"
    return error


class PowerPetDoorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for power pet door integration."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> PowerPetDoorOptionsFlow:
        """Return options handler"""
        return PowerPetDoorOptionsFlow(config_entry)

    async def async_step_import(self, config: dict[str, Any]) -> FlowResult:
        """Import a configuration from config.yaml."""

        host = config.get(CONF_HOST)
        port = config.get(CONF_PORT)
        self._async_abort_entries_match({CONF_HOST: host, CONF_PORT: port})
        return await self.async_step_user(user_input=config)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None, errors: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is not None:
            # Fake show_advanced_options ...
            if user_input.get("advanced", False):
                return await self.async_step_user_advanced(user_input=user_input, errors=errors)

            return await self.async_validate_and_create(user_input=user_input)

        # if self.show_advanced_options is True:
        #     return await self.async_step_user_advanced(errors=errors)

        data_schema = vol.Schema(get_input_schema(PP_SCHEMA)) \
            .extend({vol.Required("advanced", default=False): cv.boolean})
        return self.async_show_form(step_id="user", data_schema=data_schema, errors=errors)

    async def async_step_user_advanced(
            self, user_input: dict[str, Any] | None = None, errors: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None and not user_input.get("advanced", False):
            return await self.async_validate_and_create(user_input=user_input)

        data_schema = vol.Schema(get_input_schema(PP_SCHEMA, defaults=user_input)) \
            .extend(get_input_schema(PP_SCHEMA_ADV)) \
            .extend(get_input_schema(PP_OPT_SCHEMA))

        return self.async_show_form(step_id="user_advanced", data_schema=data_schema, errors=errors)

    async def async_validate_and_create(
            self, user_input: dict[str, Any] | None = None, errors: dict[str, Any] | None = None
    ) -> FlowResult:
        data = {}
        for schema in (PP_SCHEMA, PP_SCHEMA_ADV):
            for entry in schema:
                data[entry["field"]] = user_input.get(entry["field"], entry.get("default"))

        options = {}
        for entry in PP_OPT_SCHEMA:
            options[entry["field"]] = user_input.get(entry["field"], entry.get("default"))

        name = data.get(CONF_NAME)
        host = data.get(CONF_HOST)
        port = data.get(CONF_PORT, DEFAULT_PORT)

        error = await validate_connection(host, port)
        if error:
            if self.show_advanced_options:
                return await self.async_step_user_advanced(errors={"base": error})
            return await self.async_step_user(errors={"base": error})

        else:
            await self.async_set_unique_id(host + ":" + str(port))
            self._abort_if_unique_id_configured()

            return self.async_create_entry(title=name, data=data, options=options)


    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle reconfiguration of the integration."""
        reconfigure_entry = self._get_reconfigure_entry()

        if user_input is not None:
            host = user_input.get(CONF_HOST)
            port = user_input.get(CONF_PORT, DEFAULT_PORT)
            name = user_input.get(CONF_NAME, reconfigure_entry.data.get(CONF_NAME))

            error = await validate_connection(host, port)
            if error:
                return self.async_show_form(
                    step_id="reconfigure",
                    data_schema=vol.Schema(get_input_schema(PP_SCHEMA, defaults=user_input))
                        .extend(get_input_schema(PP_SCHEMA_ADV, defaults=user_input)),
                    errors={"base": error},
                )

            # Update the config entry
            new_data = {**reconfigure_entry.data, **user_input}
            # Update unique_id if host/port changed
            new_unique_id = f"{host}:{port}"

            return self.async_update_reload_and_abort(
                reconfigure_entry,
                unique_id=new_unique_id,
                title=name,
                data=new_data,
            )

        # Pre-fill with current values
        current_data = {**reconfigure_entry.data}
        data_schema = vol.Schema(get_input_schema(PP_SCHEMA, defaults=current_data)) \
            .extend(get_input_schema(PP_SCHEMA_ADV, defaults=current_data))

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=data_schema,
        )


class PowerPetDoorOptionsFlow(config_entries.OptionsFlow):
    """Handle a option config for power pet door integration."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.title = entry.title
        self.options = entry.options

    async def async_step_init(
            self, user_input: dict[str, Any] | None = None, errors: dict[str, Any] | None = None
    ) -> FlowResult:
        return await self.async_step_user(user_input=user_input, errors=errors)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None, errors: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is not None:
            return self.async_create_entry(title=self.title, data=user_input)

        data_schema = vol.Schema(get_input_schema(PP_OPT_SCHEMA, defaults=self.options))
        return self.async_show_form(step_id="user", data_schema=data_schema, errors=errors)
