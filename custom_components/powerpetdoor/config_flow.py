"""Adds config flow for power pet door integration."""
from __future__ import annotations

import asyncio
import contextlib
import json
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
    SCHEMA,
    SCHEMA_ADV,
    PING,
    PONG,
)

DATA_SCHEMA = vol.Schema(CONFIG_SCHEMA)
DATA_SCHEMA_ADV = DATA_SCHEMA.extend(CONFIG_SCHEMA_ADV)

async def validate_connection(host: str, port: int) -> str | None:
    error = None
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=5.0)
        last_ping = str(round(time.time()*1000))
        try:
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

    async def async_step_import(self, config: dict[str, Any]) -> FlowResult:
        """Import a configuration from config.yaml."""

        host = config.get(CONF_HOST)
        port = config.get(CONF_PORT)
        self._async_abort_entries_match({CONF_HOST: host, CONF_PORT: port})
        return await self.async_step_user(user_input=config)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""

        errors = {}
        if user_input is not None:
            host = user_input.get(CONF_HOST)
            port = user_input.get(CONF_PORT)
            name = user_input.get(CONF_NAME)

            error = await validate_connection(host, port)
            if error:
                errors["base"] = error
            else:
                await self.async_set_unique_id(host + ":" + str(port))
                self._abort_if_unique_id_configured()

                return self.async_create_entry(title=name, data=user_input)

        if self.show_advanced_options is True:
            return self.async_show_form(step_id="user", data_schema=DATA_SCHEMA_ADV, errors=errors)

        return self.async_show_form(step_id="user", data_schema=DATA_SCHEMA, errors=errors)

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
            error = await validate_connection(host, port)
            if error:
                errors["base"] = error
            else:
                return self.async_create_entry(title=name, data=user_input)

        if self.show_advanced_options is True:
            return self.async_show_form(step_id="user", data_schema=DATA_SCHEMA_ADV, errors=errors)

        return self.async_show_form(step_id="user", data_schema=DATA_SCHEMA, errors=errors)
