"""Optional latest diary scores."""

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import SIGNAL


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [ScoreSensor(entry, kind) for kind in ("morning", "evening")],
        update_before_add=True,
    )


class ScoreSensor(SensorEntity):
    _attr_should_poll = False
    _attr_icon = "mdi:gauge"

    def __init__(self, entry, kind):
        self.runtime = entry.runtime_data
        self.kind = kind
        self._attr_unique_id = f"{entry.entry_id}_{kind}"
        self._attr_name = f"Vitality {kind} score"

    async def async_update(self):
        latest = await self.runtime.run(self.runtime.diary.latest, self.kind)
        self._attr_native_value = latest["score"] if latest else None
        self._attr_extra_state_attributes = (
            {"occurred_at": latest["occurred_at"]} if latest else {}
        )

    async def async_added_to_hass(self):
        @callback
        def changed():
            self.async_schedule_update_ha_state(force_refresh=True)

        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL, changed))
