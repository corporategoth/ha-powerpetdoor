""" Constant Variables """

DOMAIN = "powerpetdoor"

CONF_REFRESH = "refresh"
CONF_KEEP_ALIVE = "keep_alive"
CONF_RECONNECT = "reconnect"
CONF_HOLD = "hold"

DEFAULT_NAME = "Power Pet Door"
DEFAULT_PORT = 3000
DEFAULT_CONNECT_TIMEOUT = 5.0
DEFAULT_RECONNECT_TIMEOUT = 30.0
DEFAULT_KEEP_ALIVE_TIMEOUT = 30.0
DEFAULT_REFRESH_TIMEOUT = 300.0
DEFAULT_HOLD = True

ValidIpAddressRegex = r"^(([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])\.){3}([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])$"
ValidHostnameRegex = r"^(([a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9\-]*[a-zA-Z0-9])\.)*([A-Za-z0-9]|[A-Za-z0-9][A-Za-z0-9\-]*[A-Za-z0-9])$"
