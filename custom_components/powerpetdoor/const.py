""" Constant Variables """

from homeassistant.const import (
    CONF_NAME,
    CONF_HOST,
    CONF_PORT,
    CONF_TIMEOUT,
    ATTR_ENTITY_ID,
    SERVICE_TOGGLE,
    SERVICE_OPEN,
    SERVICE_CLOSE,
)

DOMAIN = "powerpetdoor"

CONF_REFRESH = "refresh"
CONF_UPDATE = "update"
CONF_KEEP_ALIVE = "keep_alive"
CONF_RECONNECT = "reconnect"
CONF_HOLD = "hold"

STATE_LAST_CHANGE = "last_change"
STATE_BATTERY_CHARGING = "battery_charging"
STATE_BATTERY_DISCHARGING = "battery_discharging"

DEFAULT_NAME = "Power Pet Door"
DEFAULT_PORT = 3000
DEFAULT_CONNECT_TIMEOUT = 10.0
DEFAULT_RECONNECT_TIMEOUT = 5.0
DEFAULT_KEEP_ALIVE_TIMEOUT = 30.0
DEFAULT_REFRESH_TIMEOUT = 300.0
DEFAULT_HOLD = True
MINIMUM_TIME_BETWEEN_MSGS = 0.250

COMMAND = "cmd"
CONFIG = "config"
PING = "PING"
PONG = "PONG"
DOOR_STATUS = "DOOR_STATUS"

FIELD_POWER = "power_state"
FIELD_INSIDE = "inside"
FIELD_OUTSIDE = "outside"
FIELD_AUTO = "timersEnabled"
FIELD_SETTINGS = "settings"
FIELD_DOOR_STATUS = "door_status"
FIELD_SUCCESS = "success"
FIELD_FWINFO = "fwInfo"
FIELD_BATTERY_PERCENT = "batteryPercent"
FIELD_BATTERY_PRESENT = "batteryPresent"
FIELD_AC_PRESENT = "acPresent"
FIELD_FW_VER = "ver"
FIELD_FW_REV = "rev"
FIELD_FW_MAJOR = "fw_maj"
FIELD_FW_MINOR = "fw_min"
FIELD_FW_PATCH = "fw_pat"

DOOR_STATE_IDLE = "DOOR_IDLE"
DOOR_STATE_CLOSED = "DOOR_CLOSED"
DOOR_STATE_HOLDING = "DOOR_HOLDING"
DOOR_STATE_KEEPUP = "DOOR_KEEPUP"
DOOR_STATE_RISING = "DOOR_RISING"
DOOR_STATE_SLOWING = "DOOR_SLOWING"
DOOR_STATE_TOP_OPEN = "DOOR_TOP_OPEN"
DOOR_STATE_MID_OPEN = "DOOR_MID_OPEN"

CMD_OPEN = "OPEN"
CMD_OPEN_AND_HOLD = "OPEN_AND_HOLD"
CMD_CLOSE = "CLOSE"
CMD_GET_SETTINGS = "GET_SETTINGS"
CMD_GET_SENSORS = "GET_SENSORS"
CMD_GET_POWER = "GET_POWER"
CMD_GET_AUTO = "GET_TIMERS_ENABLED"
CMD_GET_DOOR_STATUS = "GET_DOOR_STATUS"
CMD_DISABLE_INSIDE = "DISABLE_INSIDE"
CMD_ENABLE_INSIDE = "ENABLE_INSIDE"
CMD_DISABLE_OUTSIDE = "DISABLE_OUTSIDE"
CMD_ENABLE_OUTSIDE = "ENABLE_OUTSIDE"
CMD_DISABLE_AUTO = "DISABLE_TIMERS"
CMD_ENABLE_AUTO = "ENABLE_TIMERS"
CMD_POWER_ON = "POWER_ON"
CMD_POWER_OFF = "POWER_OFF"
CMD_GET_HW_INFO = "GET_HW_INFO"
CMD_GET_DOOR_BATTERY = "GET_DOOR_BATTERY"
CMD_HAS_REMOTE_ID = "HAS_REMOTE_ID"
CMD_HAS_REMOTE_KEY = "HAS_REMOTE_KEY"
CMD_CHECK_RESET_REASON = "CHECK_RESET_REASON"

ValidIpAddressRegex = r"^(([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])\.){3}([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])$"
ValidHostnameRegex = r"^(([a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9\-]*[a-zA-Z0-9])\.)*([A-Za-z0-9]|[A-Za-z0-9][A-Za-z0-9\-]*[A-Za-z0-9])$"
