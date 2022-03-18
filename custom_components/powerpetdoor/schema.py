from typing import TypedDict, Any
from homeassistant.config_entries import ConfigEntry
import homeassistant.helpers.config_validation as cv
import voluptuous as vol

from .const import (
    CONF_NAME,
    CONF_HOST,
    CONF_HOLD,
    CONF_PORT,
    CONF_TIMEOUT,
    CONF_RECONNECT,
    CONF_KEEP_ALIVE,
    CONF_REFRESH,
    CONF_UPDATE,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_RECONNECT_TIMEOUT,
    DEFAULT_KEEP_ALIVE_TIMEOUT,
    DEFAULT_REFRESH_TIMEOUT,
    DEFAULT_HOLD,
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
    validting_schema: Any

PP_SCHEMA: list[Entry] = [
    Entry(
        field = CONF_NAME,
        optional = True,
        default = DEFAULT_NAME,
        input_schema = cv.string
    ),
    Entry(
        field = CONF_HOST,
        optional = False,
        input_schema = cv.string,
        validating_schema = vol.All(cv.string, vol.Any(vol.Match(ValidIpAddressRegex),
                                                      vol.Match(ValidHostnameRegex))),
    ),
    Entry(
        field = CONF_HOLD,
        optional = True,
        default = DEFAULT_HOLD,
        input_schema = bool
    ),
]

PP_SCHEMA_ADV: list[Entry] = [
    Entry(
        field = CONF_PORT,
        optional = True,
        default = DEFAULT_PORT,
        input_schema = cv.port
    ),
    Entry(
        field = CONF_TIMEOUT,
        optional = False,
        default = DEFAULT_CONNECT_TIMEOUT,
        input_schema = vol.Coerce(float)
    ),
    Entry(
        field = CONF_RECONNECT,
        optional = False,
        default = DEFAULT_RECONNECT_TIMEOUT,
        input_schema = vol.Coerce(float)
    ),
    Entry(
        field = CONF_KEEP_ALIVE,
        optional = False,
        default = DEFAULT_KEEP_ALIVE_TIMEOUT,
        input_schema = vol.Coerce(float)
    ),
    Entry(
        field = CONF_REFRESH,
        optional = True,
        default = DEFAULT_REFRESH_TIMEOUT,
        input_schema = vol.Coerce(float)
    ),
    Entry(
        field = CONF_UPDATE,
        optional = True,
        input_schema = vol.Coerce(float)
    ),
]

def get_input_schema(schema: list[Entry],
                     excluded: set[str] = {},
                     defaults: ConfigEntry = None) -> dict:
    rv = {}
    for entry in schema:
        if not entry["field"] in excluded:
            field = None
            default = None
            if defaults is not None and entry["field"] in defaults.data:
                default = defaults.data[entry["field"]]
            elif "default" in entry:
                default = entry["default"]
            if entry["optional"]:
                field = vol.Optional(entry["field"], default=default,
                                     description = entry["description"] if "description" in entry else None,
                                     msg = entry["msg"] if "msg" in entry else None)
            else:
                field = vol.Required(entry["field"], default=default,
                                     description = entry["description"] if "description" in entry else None,
                                     msg = entry["msg"] if "msg" in entry else None)
            rv[field] = entry["input_schema"]
    return rv

def get_validating_schema(schema: list[Entry],
                          excluded: set[str] = {},
                          defaults: ConfigEntry = None) -> dict:
    rv = {}
    for entry in schema:
        if not entry["field"] in excluded:
            field = None
            default = None
            if defaults and entry["field"] in defaults.data:
                default = defaults.data[entry["field"]]
            elif "default" in entry:
                default = entry["default"]
            if entry["optional"]:
                field = vol.Optional(entry["field"], default=default,
                                     description = entry["description"] if "description" in entry else None,
                                     msg = entry["msg"] if "msg" in entry else None)
            else:
                field = vol.Required(entry["field"], default=default,
                                     description = entry["description"] if "description" in entry else None,
                                     msg = entry["msg"] if "msg" in entry else None)
            if "validating_schema" in entry:
                rv[field] = entry["validating_schema"]
            else:
                rv[field] = entry["input_schema"]
    return rv
