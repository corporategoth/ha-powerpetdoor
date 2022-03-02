""" Power Pet Door """

from homeassistant.const import Platform

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.config_entries.async_setup_platforms(entry, [ Platform.SWITCH ])

    return True
