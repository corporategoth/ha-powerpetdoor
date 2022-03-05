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

class Entry(TypeDict):
    field: str
    description: str | None = None
    msg: msg | None = None
    optional: bool
    default: Any | None = None
    input_schema: Any
    validting_schema: Any | None = None

PP_SCHEMA: list[Entry] = {
    {
        field: CONF_NAME,
        optional: True,
        default: DEFAULT_NAME,
        input_schema: cv.string
    },
    {
        field: CONF_HOST,
        optional: False,
        input_schema: cv.string,
        validating_schema: vol.All(cv.string, vol.Any(vol.Match(ValidIpAddressRegex),
                                                      vol.Match(ValidHostnameRegex))),
    },
    {
        field: CONF_HOLD,
        optional: True,
        default: DEFAULT_HOLD,
        input_schema: bool
    },
}

PP_SCHEMA_ADV: list[Entry] = {
    {
        field: CONF_PORT,
        optional: True,
        default: DEFAULT_PORT,
        input_schema: cv.port
    },
    {
        field: CONF_TIMEOUT,
        optional: False,
        default: DEFAULT_TIMEOUT,
        input_schema: vol.Coerce(float)
    },
    {
        field: CONF_RECONNECT,
        optional: False,
        default: DEFAULT_RECONNECT,
        input_schema: vol.Coerce(float)
    },
    {
        field: CONF_KEEP_ALIVE,
        optional: False,
        default: DEFAULT_KEEP_ALOVE,
        input_schema: vol.Coerce(float)
    },
    {
        field: CONF_REFRESH,
        optional: True,
        default: DEFAULT_REFRESH,
        input_schema: vol.Coerce(float)
    },
    {
        field: CONF_UPDATE,
        optional: True,
        default: DEFAULT_UPDATE,
        input_schema: vol.Coerce(float)
    },
}

def get_input_schema(schema: list[Entry],
                     excluded: set[str] = {},
                     defaults: ConfigEntry | None = None) -> dict:
    rv = {}
    for entry in schema:
        if not entry["field"] in excluded:
            field = None
            default = UNDEFINED
            if defaults and entry["field"] in defaults:
                default = defaults[entry["field"]]
            elif entry["default"] is not None:
                default = entry["default"]
            if entry["optional"]:
                field = vol.Optional(entry["field"], default=default, description=entry["description"], msg=entry["msg"])
            else:
                field = vol.Required(entry["field"], default=default, description=entry["description"], msg=entry["msg"])
            rv[field] = entry["input_schema"]
    return rv

def get_validating_schema(schema: list[Entry],
                          excluded: set[str] = {},
                          defaults: ConfigEntry | None = None) -> dict:
    rv = {}
    for entry in schema:
        if not entry["field"] in excluded:
            field = None
            default = UNDEFINED
            if defaults and entry["field"] in defaults:
                default = defaults[entry["field"]]
            elif entry["default"] is not None:
                default = entry["default"]
            if entry["optional"]:
                field = vol.Optional(entry["field"], default=default, description=entry["description"], msg=entry["msg"])
            else:
                field = vol.Required(entry["field"], default=default, description=entry["description"], msg=entry["msg"])
            if entry["validating_schema"] is not None:
                rv[field] = entry["validating_schema"]
            else:
                rv[field] = entry["input_schema"]
    return rv
