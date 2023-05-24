""" Constant Variables """

from homeassistant.const import (
    CONF_NAME,
    CONF_HOST,
    CONF_PORT,
    CONF_ICON,
    CONF_ID,
    CONF_TIMEOUT,
    ATTR_ENTITY_ID,
)

DOMAIN = "powerpetdoor"

CONF_REFRESH = "refresh"
CONF_UPDATE = "update"
CONF_KEEP_ALIVE = "keep_alive"
CONF_RECONNECT = "reconnect"
CONF_HOLD_MIN = "hold_min"
CONF_HOLD_MAX = "hold_max"
CONF_HOLD_STEP = "hold_step"

STATE_LAST_CHANGE = "last_change"
STATE_BATTERY_CHARGING = "battery_charging"
STATE_BATTERY_DISCHARGING = "battery_discharging"

DEFAULT_NAME = "Power Pet Door"
DEFAULT_PORT = 3000
DEFAULT_CONNECT_TIMEOUT = 10.0
DEFAULT_RECONNECT_TIMEOUT = 5.0
DEFAULT_KEEP_ALIVE_TIMEOUT = 30.0
DEFAULT_REFRESH_TIMEOUT = 300.0
MINIMUM_TIME_BETWEEN_MSGS = 0.200

# These values mirror the app.  Though the actual value can be a MUCH broader range.
DEFAULT_HOLD_MIN = 2
DEFAULT_HOLD_MAX = 8
DEFAULT_HOLD_STEP = 2

COMMAND = "cmd"
CONFIG = "config"
PING = "PING"
PONG = "PONG"
DOOR_STATUS = "DOOR_STATUS"

FIELD_POWER = "power_state"
FIELD_INSIDE = "inside"
FIELD_OUTSIDE = "outside"
FIELD_AUTO = "timersEnabled"
FIELD_OUTSIDE_SENSOR_SAFETY_LOCK = "outsideSensorSafetyLock"
FIELD_CMD_LOCKOUT = "allowCmdLockout"
FIELD_AUTORETRACT = "doorOptions"
FIELD_TOTAL_OPEN_CYCLES = "totalOpenCycles"
FIELD_TOTAL_AUTO_RETRACTS = "totalAutoRetracts"
FIELD_SETTINGS = "settings"
FIELD_NOTIFICATIONS = "notifications"
FIELD_TZ = "tz"
FIELD_SCHEDULE = "schedule"
FIELD_SCHEDULES = "schedules"
FIELD_INDEX = "index"
FIELD_ENABLED = "enabled"
FIELD_DAYSOFWEEK = "daysOfWeek"
FIELD_INSIDE_PREFIX = "in"
FIELD_OUTSIDE_PREFIX = "out"
FIELD_START_TIME_SUFFIX = "_start_time"
FIELD_END_TIME_SUFFIX = "_end_time"
FIELD_HOUR = "hour"
FIELD_MINUTE = "min"
FIELD_VOLTAGE = "voltage"
FIELD_HOLD_TIME = "holdTime"
FIELD_HOLD_OPEN_TIME = "holdOpenTime"
FIELD_SENSOR_TRIGGER_VOLTAGE = "sensorTriggerVoltage"
FIELD_SLEEP_SENSOR_TRIGGER_VOLTAGE = "sleepSensorTriggerVoltage"
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
FIELD_SENSOR_ON_INDOOR_NOTIFICATIONS = "sensorOnIndoorNotificationsEnabled"
FIELD_SENSOR_OFF_INDOOR_NOTIFICATIONS = "sensorOffIndoorNotificationsEnabled"
FIELD_SENSOR_ON_OUTDOOR_NOTIFICATIONS = "sensorOnOutdoorNotificationsEnabled"
FIELD_SENSOR_OFF_OUTDOOR_NOTIFICATIONS = "sensorOffOutdoorNotificationsEnabled"
FIELD_LOW_BATTERY_NOTIFICATIONS = "lowBatteryNotificationsEnabled"

DOOR_STATE_IDLE = "DOOR_IDLE"
DOOR_STATE_CLOSED = "DOOR_CLOSED"
DOOR_STATE_HOLDING = "DOOR_HOLDING"
DOOR_STATE_KEEPUP = "DOOR_KEEPUP"
DOOR_STATE_RISING = "DOOR_RISING"
DOOR_STATE_SLOWING = "DOOR_SLOWING"
DOOR_STATE_CLOSING_TOP_OPEN = "DOOR_CLOSING_TOP_OPEN"
DOOR_STATE_CLOSING_MID_OPEN = "DOOR_CLOSING_MID_OPEN"

CMD_OPEN = "OPEN"
CMD_OPEN_AND_HOLD = "OPEN_AND_HOLD"
CMD_CLOSE = "CLOSE"
CMD_GET_SETTINGS = "GET_SETTINGS"
CMD_GET_SENSORS = "GET_SENSORS"
CMD_GET_POWER = "GET_POWER"
CMD_GET_AUTO = "GET_TIMERS_ENABLED"
CMD_GET_OUTSIDE_SENSOR_SAFETY_LOCK = "GET_OUTSIDE_SENSOR_SAFETY_LOCK"
CMD_GET_CMD_LOCKOUT = "GET_CMD_LOCKOUT"
CMD_GET_AUTORETRACT = "GET_AUTORETRACT"
CMD_GET_DOOR_STATUS = "GET_DOOR_STATUS"
CMD_GET_DOOR_OPEN_STATS = "GET_DOOR_OPEN_STATS"
CMD_DISABLE_INSIDE = "DISABLE_INSIDE"
CMD_ENABLE_INSIDE = "ENABLE_INSIDE"
CMD_DISABLE_OUTSIDE = "DISABLE_OUTSIDE"
CMD_ENABLE_OUTSIDE = "ENABLE_OUTSIDE"
CMD_DISABLE_AUTO = "DISABLE_TIMERS"
CMD_ENABLE_AUTO = "ENABLE_TIMERS"
CMD_DISABLE_OUTSIDE_SENSOR_SAFETY_LOCK = "DISABLE_OUTSIDE_SENSOR_SAFETY_LOCK"
CMD_ENABLE_OUTSIDE_SENSOR_SAFETY_LOCK = "ENABLE_OUTSIDE_SENSOR_SAFETY_LOCK"
CMD_DISABLE_CMD_LOCKOUT = "DISABLE_CMD_LOCKOUT"
CMD_ENABLE_CMD_LOCKOUT = "ENABLE_CMD_LOCKOUT"
CMD_DISABLE_AUTORETRACT = "DISABLE_AUTORETRACT"
CMD_ENABLE_AUTORETRACT = "ENABLE_AUTORETRACT"
CMD_POWER_ON = "POWER_ON"
CMD_POWER_OFF = "POWER_OFF"
CMD_GET_HW_INFO = "GET_HW_INFO"
CMD_GET_DOOR_BATTERY = "GET_DOOR_BATTERY"
CMD_HAS_REMOTE_ID = "HAS_REMOTE_ID"
CMD_HAS_REMOTE_KEY = "HAS_REMOTE_KEY"
CMD_CHECK_RESET_REASON = "CHECK_RESET_REASON"

CMD_GET_NOTIFICATIONS = "GET_NOTIFICATIONS"
CMD_SET_NOTIFICATIONS = "SET_NOTIFICATIONS"
CMD_GET_HOLD_TIME = "GET_HOLD_TIME"
CMD_SET_HOLD_TIME = "SET_HOLD_TIME"
CMD_GET_TIMEZONE = "GET_TIMEZONE"
CMD_SET_TIMEZONE = "SET_TIMEZONE"
CMD_GET_SENSOR_TRIGGER_VOLTAGE = "GET_SENSOR_TRIGGER_VOLTAGE"
CMD_SET_SENSOR_TRIGGER_VOLTAGE = "SET_SENSOR_TRIGGER_VOLTAGE"
CMD_GET_SLEEP_SENSOR_TRIGGER_VOLTAGE = "GET_SLEEP_SENSOR_TRIGGER_VOLTAGE"
CMD_SET_SLEEP_SENSOR_TRIGGER_VOLTAGE = "SET_SLEEP_SENSOR_TRIGGER_VOLTAGE"

CMD_GET_SCHEDULE_LIST = "GET_SCHEDULE_LIST"
CMD_SET_SCHEDULE_LIST = "SET_SCHEDULE_LIST"
CMD_GET_SCHEDULE = "GET_SCHEDULE"
CMD_SET_SCHEDULE = "SET_SCHEDULE"
CMD_DELETE_SCHEDULE = "DELETE_SCHEDULE"

ValidIpAddressRegex = r"^(([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])\.){3}([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])$"
ValidHostnameRegex = r"^(([a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9\-]*[a-zA-Z0-9])\.)*([A-Za-z0-9]|[A-Za-z0-9][A-Za-z0-9\-]*[A-Za-z0-9])$"
ValidTZRegex = r"^$"