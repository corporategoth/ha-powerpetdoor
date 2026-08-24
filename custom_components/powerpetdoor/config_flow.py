# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""Config flow for the Power Pet Door integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT, CONF_TIMEOUT
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)
from powerpetdoor import CommandError, PowerPetDoor

from .const import (
    CONF_HOLD_MAX,
    CONF_HOLD_MIN,
    CONF_HOLD_STEP,
    CONF_KEEP_ALIVE,
    CONF_RECONNECT,
    CONF_REFRESH,
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_HOLD_MAX,
    DEFAULT_HOLD_MIN,
    DEFAULT_HOLD_STEP,
    DEFAULT_KEEP_ALIVE_TIMEOUT,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DEFAULT_RECONNECT_TIMEOUT,
    DEFAULT_REFRESH_TIMEOUT,
    DOMAIN,
)
from .coordinator import PowerPetDoorConfigEntry

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Required(CONF_HOST): cv.string,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
    }
)


def _seconds(minimum: float = 0, maximum: float = 3600) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(min=minimum, max=maximum, step=0.1, mode=NumberSelectorMode.BOX)
    )


def options_schema(options: dict[str, Any]) -> vol.Schema:
    """Build the options schema, pre-filled with the current values."""
    return vol.Schema(
        {
            vol.Required(
                CONF_TIMEOUT, default=options.get(CONF_TIMEOUT, DEFAULT_CONNECT_TIMEOUT)
            ): _seconds(1),
            vol.Required(
                CONF_RECONNECT,
                default=options.get(CONF_RECONNECT, DEFAULT_RECONNECT_TIMEOUT),
            ): _seconds(1),
            vol.Required(
                CONF_KEEP_ALIVE,
                default=options.get(CONF_KEEP_ALIVE, DEFAULT_KEEP_ALIVE_TIMEOUT),
            ): _seconds(0),
            vol.Required(
                CONF_REFRESH, default=options.get(CONF_REFRESH, DEFAULT_REFRESH_TIMEOUT)
            ): _seconds(10, 86400),
            vol.Optional(
                CONF_HOLD_MIN, default=options.get(CONF_HOLD_MIN, DEFAULT_HOLD_MIN)
            ): _seconds(0, 600),
            vol.Optional(
                CONF_HOLD_MAX, default=options.get(CONF_HOLD_MAX, DEFAULT_HOLD_MAX)
            ): _seconds(0, 600),
            vol.Optional(
                CONF_HOLD_STEP, default=options.get(CONF_HOLD_STEP, DEFAULT_HOLD_STEP)
            ): _seconds(0.1, 60),
        }
    )


async def async_validate_connection(host: str, port: int) -> str | None:
    """Try to talk to a door; return an error key, or None on success.

    Uses the library rather than opening a socket and hand-writing a PING.
    The previous implementation did the latter, with four bare `except:`
    clauses that swallowed `KeyboardInterrupt` and `asyncio.CancelledError`
    along with everything else, and it duplicated framing rules that only
    `pypowerpetdoor` should know. Connecting the way the integration
    actually connects also means this test fails for the same reasons real
    operation would, instead of for its own.
    """
    door = PowerPetDoor(host=host, port=port, timeout=DEFAULT_CONNECT_TIMEOUT, keepalive=0)
    try:
        await door.connect()
        # `connect()` only establishes TCP, and `refresh()` gathers with
        # return_exceptions=True and merely logs - so on their own they
        # report success for ANY listener at that address. A user who
        # typos an octet, or points this at their NAS, would get a created
        # entry and ~25 entities showing the facade's constructor defaults
        # (cover closed, power on, battery 100%) with available=True.
        #
        # `refresh_status()` actually awaits a reply and raises if none
        # comes, so it is what makes this a test of "is there a DOOR here"
        # rather than "is something listening". It is also what makes the
        # timeout_connect and invalid_response branches below reachable at
        # all; without it they were dead code and their strings.json
        # entries described errors that could never occur.
        await door.refresh_status()
    except TimeoutError:
        return "timeout_connect"
    except (CommandError, ValueError):
        # Reached the port and got something back that was not a door.
        return "invalid_response"
    except OSError:
        return "cannot_connect"
    else:
        return None
    finally:
        # Always: a successful connect leaves a socket and a keepalive task
        # behind, and the flow may still abort afterwards on a duplicate
        # unique_id.
        await door.disconnect()


class PowerPetDoorConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for the Power Pet Door."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: PowerPetDoorConfigEntry,
    ) -> PowerPetDoorOptionsFlow:
        """Return the options flow handler."""
        return PowerPetDoorOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]

            # Before dialling: a door already configured must abort rather
            # than be set up twice, which is what produced two entries
            # fighting over one device in issue #9.
            await self.async_set_unique_id(f"{host}:{port}")
            self._abort_if_unique_id_configured()

            error = await async_validate_connection(host, port)
            if error is None:
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data={CONF_HOST: host, CONF_PORT: port, CONF_NAME: user_input[CONF_NAME]},
                    options=_default_options(),
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(STEP_USER_SCHEMA, user_input or {}),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle moving an existing door to a new address."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]

            # NOT `_abort_if_unique_id_mismatch`. That helper is for
            # integrations whose unique_id comes from the DEVICE - a serial
            # number you re-read to confirm you are still talking to the
            # same unit. Ours IS the address, so moving a door necessarily
            # changes it, and asserting it had not changed made this step
            # abort on precisely the edit it exists to perform. Reconfigure
            # could not reconfigure anything.
            #
            # What must still be prevented is pointing this entry at an
            # address some OTHER entry already owns, which would leave two
            # entries fighting over one door (issue #9).
            unique_id = f"{host}:{port}"
            if any(
                other.entry_id != entry.entry_id and other.unique_id == unique_id
                for other in self._async_current_entries()
            ):
                return self.async_abort(reason="already_configured")

            error = await async_validate_connection(host, port)
            if error is None:
                # Before the reload, not after: the entities come back under
                # their new unique_ids the moment the entry reloads, and
                # anything not renamed by then is a duplicate.
                await _async_migrate_identifiers(
                    self.hass,
                    entry,
                    f"{entry.data[CONF_HOST]}:{entry.data[CONF_PORT]}",
                    unique_id,
                )
                return self.async_update_reload_and_abort(
                    entry,
                    # The unique_id moves with the address, or the entry
                    # would keep claiming the old one and a later setup of
                    # the real door at that address would be refused.
                    unique_id=unique_id,
                    title=user_input[CONF_NAME],
                    data_updates={
                        CONF_HOST: host,
                        CONF_PORT: port,
                        CONF_NAME: user_input[CONF_NAME],
                    },
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA, user_input or dict(entry.data)
            ),
            errors=errors,
        )


class PowerPetDoorOptionsFlow(OptionsFlow):
    """Handle the Power Pet Door options."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            # A hold range whose minimum exceeds its maximum produces a
            # number entity Home Assistant refuses to render, with no
            # explanation. Caught here, where the user can still fix it.
            if user_input[CONF_HOLD_MIN] > user_input[CONF_HOLD_MAX]:
                errors[CONF_HOLD_MIN] = "hold_range_inverted"
            else:
                return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema({**self.config_entry.options, **(user_input or {})}),
            errors=errors,
        )


async def _async_migrate_identifiers(
    hass: HomeAssistant,
    entry: PowerPetDoorConfigEntry,
    old: str,
    new: str,
) -> None:
    """Carry the device and every entity across a change of address.

    The device identifier and every entity unique_id are `host:port` plus a
    suffix - see `PowerPetDoorCoordinator.device_identifier`, which is that
    shape by compatibility with the releases that shipped it, not by choice.
    Moving a door is therefore the one edit that changes all of them at
    once, and without this Home Assistant files the results as NEW: a second
    device, 34 more entities each suffixed `_2`, and the originals orphaned.
    Every dashboard card, automation, script and long-term statistic would
    point at an entity id that no longer resolves.

    That is not an exotic case. A DHCP lease expiring is enough to cause it,
    and moving a door to a new address is the entire purpose of the
    reconfigure step this runs in.
    """
    if old == new:
        # The user re-submitted the form without touching the address -
        # renaming, or retrying after a failed connection.
        return

    device_registry = dr.async_get(hass)
    if (device := device_registry.async_get_device(identifiers={(DOMAIN, old)})) is not None:
        device_registry.async_update_device(device.id, new_identifiers={(DOMAIN, new)})

    prefix = f"{old}-"

    @callback
    def _migrate(registry_entry: er.RegistryEntry) -> dict[str, str] | None:
        if not registry_entry.unique_id.startswith(prefix):
            return None
        # Rebuilt from the suffix rather than str.replace: the address is a
        # substring of nothing else here today, but a suffix that happened
        # to contain it would be rewritten twice.
        return {"new_unique_id": f"{new}-{registry_entry.unique_id[len(prefix) :]}"}

    await er.async_migrate_entries(hass, entry.entry_id, _migrate)


def _default_options() -> dict[str, Any]:
    """Return the options a freshly created entry starts with."""
    return {
        CONF_TIMEOUT: DEFAULT_CONNECT_TIMEOUT,
        CONF_RECONNECT: DEFAULT_RECONNECT_TIMEOUT,
        CONF_KEEP_ALIVE: DEFAULT_KEEP_ALIVE_TIMEOUT,
        CONF_REFRESH: DEFAULT_REFRESH_TIMEOUT,
        CONF_HOLD_MIN: DEFAULT_HOLD_MIN,
        CONF_HOLD_MAX: DEFAULT_HOLD_MAX,
        CONF_HOLD_STEP: DEFAULT_HOLD_STEP,
    }
