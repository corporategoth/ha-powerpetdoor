from typing import TypedDict, Any
from types import MappingProxyType
import homeassistant.helpers.config_validation as cv
import voluptuous as vol

from .const import (
    CONF_NAME,
    CONF_HOST,
    CONF_PORT,
    CONF_TIMEOUT,
    CONF_RECONNECT,
    CONF_KEEP_ALIVE,
    CONF_REFRESH,
    CONF_UPDATE,
    CONF_HOLD_MIN,
    CONF_HOLD_MAX,
    CONF_HOLD_STEP,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_RECONNECT_TIMEOUT,
    DEFAULT_KEEP_ALIVE_TIMEOUT,
    DEFAULT_REFRESH_TIMEOUT,
    DEFAULT_HOLD_MIN,
    DEFAULT_HOLD_MAX,
    DEFAULT_HOLD_STEP,
    ValidIpAddressRegex,
    ValidHostnameRegex,
)

class Entry(TypedDict):
    field: str
    description: str
    msg: str
    optional: bool
    default: Any
    input_schema: Any
    validating_schema: Any

PP_SCHEMA: list[Entry] = [
    Entry(
        field=CONF_NAME,
        optional=True,
        default=DEFAULT_NAME,
        input_schema=cv.string
    ),
    Entry(
        field=CONF_HOST,
        optional=False,
        input_schema=cv.string,
        validating_schema=vol.All(cv.string, vol.Any(vol.Match(ValidIpAddressRegex),
                                                     vol.Match(ValidHostnameRegex))),
    ),
]

PP_SCHEMA_ADV: list[Entry] = [
    Entry(
        field=CONF_PORT,
        optional=True,
        default=DEFAULT_PORT,
        input_schema=cv.port
    ),
]

PP_OPT_SCHEMA: list[Entry] = [
    Entry(
        field=CONF_TIMEOUT,
        optional=False,
        default=DEFAULT_CONNECT_TIMEOUT,
        input_schema=vol.Coerce(float)
    ),
    Entry(
        field=CONF_RECONNECT,
        optional=False,
        default=DEFAULT_RECONNECT_TIMEOUT,
        input_schema=vol.Coerce(float)
    ),
    Entry(
        field=CONF_KEEP_ALIVE,
        optional=False,
        default=DEFAULT_KEEP_ALIVE_TIMEOUT,
        input_schema=vol.Coerce(float)
    ),
    Entry(
        field=CONF_REFRESH,
        optional=True,
        default=DEFAULT_REFRESH_TIMEOUT,
        input_schema=vol.Coerce(float)
    ),
    Entry(
        field=CONF_UPDATE,
        optional=True,
        default=0,
        input_schema=vol.Coerce(float)
    ),
    Entry(
        field=CONF_HOLD_MIN,
        optional=True,
        default=DEFAULT_HOLD_MIN,
        input_schema=vol.Coerce(float)
    ),
    Entry(
        field=CONF_HOLD_MAX,
        optional=True,
        default=DEFAULT_HOLD_MAX,
        input_schema=vol.Coerce(float)
    ),
    Entry(
        field=CONF_HOLD_STEP,
        optional=True,
        default=DEFAULT_HOLD_STEP,
        input_schema=vol.Coerce(float)
    ),
]

def get_input_schema(schema: list[Entry],
                     excluded: set[str] = {},
                     defaults: MappingProxyType[str, Any] | None = None) -> dict:
    rv = {}
    for entry in schema:
        if not entry["field"] in excluded:
            if defaults:
                default = defaults.get(entry["field"], entry.get("default"))
            else:
                default = entry.get("default")
            if entry.get("optional", True):
                field = vol.Optional(entry["field"], default=default,
                                     description=entry.get("description"),
                                     msg=entry.get("msg"))
            else:
                field = vol.Required(entry["field"], default=default,
                                     description=entry.get("description"),
                                     msg=entry.get("msg"))
            rv[field] = entry.get("input_schema")
    return rv

def get_validating_schema(schema: list[Entry],
                          excluded: set[str] = {},
                          defaults: MappingProxyType[str, Any] | None = None) -> dict:
    rv = {}
    for entry in schema:
        if not entry["field"] in excluded:
            if defaults:
                default = defaults.get(entry["field"], entry.get("default"))
            else:
                default = entry.get("default")
            if entry.get("optional", True):
                field = vol.Optional(entry["field"], default=default,
                                     description=entry.get("description"),
                                     msg=entry.get("msg"))
            else:
                field = vol.Required(entry["field"], default=default,
                                     description=entry.get("description"),
                                     msg=entry.get("msg"))
            rv[field] = entry.get("validating_schema", entry.get("input_schema"))
    return rv
