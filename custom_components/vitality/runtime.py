"""Config entry lifecycle and executor boundary."""

import sqlite3
from zoneinfo import ZoneInfo

from homeassistant.const import Platform
from homeassistant.exceptions import ConfigEntryError, HomeAssistantError

from .const import DB_NAME, DOMAIN
from .garmin import Garmin
from .storage import Diary
from .validation import Invalid


class Runtime:
    def __init__(self, hass):
        self.hass = hass
        self.zone = ZoneInfo(hass.config.time_zone)
        self.diary = Diary(hass.config.path(DB_NAME))
        self.platforms = []
        self.closing = False
        self.garmin = Garmin(self)

    async def run(self, function, *args):
        if self.closing:
            raise HomeAssistantError(
                "Vitality is unloading. Try again after it reloads."
            )
        try:
            return await self.hass.async_add_executor_job(function, *args)
        except Invalid as err:
            raise HomeAssistantError(str(err)) from err
        except sqlite3.Error:
            raise HomeAssistantError(
                "Vitality could not access its database. Check storage and try again."
            ) from None


async def setup_entry(hass, entry):
    runtime = Runtime(hass)
    try:
        await runtime.run(runtime.diary.initialize)
    except HomeAssistantError as err:
        raise ConfigEntryError(str(err)) from err
    entry.runtime_data = runtime
    if any(
        entry.options.get(key, entry.data.get(key, False))
        for key in ("expose_scores", "expose_stats")
    ):
        runtime.platforms = [Platform.SENSOR]
        await hass.config_entries.async_forward_entry_setups(entry, runtime.platforms)
    hass.data[DOMAIN] = runtime
    try:
        await runtime.garmin.start()
    except HomeAssistantError as err:
        hass.data.pop(DOMAIN, None)
        if runtime.platforms:
            await hass.config_entries.async_unload_platforms(entry, runtime.platforms)
        raise ConfigEntryError(str(err)) from err
    return True


async def unload_entry(hass, entry):
    runtime = entry.runtime_data
    if runtime.platforms and not await hass.config_entries.async_unload_platforms(
        entry, runtime.platforms
    ):
        return False
    await runtime.garmin.close()
    runtime.closing = True
    hass.data.pop(DOMAIN, None)
    return True
