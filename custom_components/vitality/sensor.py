"""Optional latest diary scores and calendar summaries."""

import logging
from datetime import UTC, datetime, timedelta
from statistics import mean

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import SIGNAL
from .queries import daily
from .validation import bounds

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    if entry.options.get("expose_scores", entry.data.get("expose_scores", False)):
        async_add_entities(
            [ScoreSensor(entry, kind) for kind in ("morning", "evening")],
            update_before_add=True,
        )
    if not entry.options.get("expose_stats", entry.data.get("expose_stats", False)):
        return

    runtime = entry.runtime_data

    async def update():
        try:
            return await runtime.run(
                summary, runtime.diary, runtime.zone, datetime.now(UTC)
            )
        except HomeAssistantError as err:
            raise UpdateFailed(str(err)) from err

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        config_entry=entry,
        name="Vitality statistics",
        update_method=update,
        always_update=False,
    )
    await coordinator.async_config_entry_first_refresh()
    known = set()

    @callback
    def add_stats():
        sensors = []
        for key, (name, _, _) in coordinator.data.items():
            if key not in known:
                known.add(key)
                sensors.append(StatsSensor(coordinator, entry.entry_id, key, name))
        if sensors:
            async_add_entities(sensors)

    @callback
    def changed(*_):
        hass.async_create_task(coordinator.async_request_refresh())

    add_stats()
    entry.async_on_unload(coordinator.async_add_listener(add_stats))
    entry.async_on_unload(async_dispatcher_connect(hass, SIGNAL, changed))
    entry.async_on_unload(
        async_track_time_change(hass, changed, hour=0, minute=0, second=0)
    )


def summary(diary, zone, now):
    today = now.astimezone(zone).date()
    start = (today - timedelta(days=6)).isoformat()
    end = today.isoformat()
    days = daily(diary, zone, {"start": start, "end": end})
    current = days[-1]
    date = {"date": end}
    week = {"start_date": start, "end_date": end}
    result = {
        "activities_today": ("Activities today", current["count"], date),
        "activities_7_days": (
            "Activities last 7 days",
            sum(row["count"] for row in days),
            week,
        ),
        "workouts_today": ("Garmin workouts today", current["workout_count"], date),
        "mood_today": (
            "Latest mood today",
            current["mood"],
            date | {"ratings": current["mood_count"]},
        ),
        "mood_average_today": (
            "Average mood today",
            round(current["mood_average"], 1) if current["mood_count"] else None,
            date | {"ratings": current["mood_count"]},
        ),
        "sleep_score_today": (
            "Garmin sleep score today",
            current["metrics"].get("sleep_score", {}).get("value"),
            date,
        ),
        "body_battery_today": (
            "Garmin Body Battery today",
            current["metrics"].get("body_battery.last", {}).get("value"),
            date,
        ),
    }
    workouts = [
        row["workout_count"] for row in days if row["workout_count"] is not None
    ]
    result["workouts_7_days"] = (
        "Garmin workouts last 7 days",
        sum(workouts) if workouts else None,
        week | {"days_with_workout_data": len(workouts)},
    )
    for kind in ("morning", "evening"):
        values = [row[kind] for row in days if row[kind] is not None]
        result[f"{kind}_today"] = (f"{kind.title()} energy today", current[kind], date)
        result[f"{kind}_7_days"] = (
            f"{kind.title()} energy last 7 days",
            round(mean(values), 1) if values else None,
            week | {"days_with_scores": len(values)},
        )
    moods = [row["mood_average"] for row in days if row["mood_count"]]
    result["mood_7_days"] = (
        "Average mood last 7 days",
        round(mean(moods), 1) if moods else None,
        week | {"days_with_ratings": len(moods)},
    )
    lower, upper = bounds(start, end, zone)
    today_lower, _ = bounds(end, end, zone)
    with diary.session() as db:
        rows = db.execute(
            """SELECT t.id, t.name, count(e.id) AS week_count,
                      count(CASE WHEN e.occurred_at>=? THEN 1 END) AS today_count
               FROM activity_types t LEFT JOIN events e
                 ON e.activity_type_id=t.id AND e.occurred_at>=? AND e.occurred_at<?
               GROUP BY t.id""",
            (today_lower, lower, upper),
        )
        for row in rows:
            result[f"activity_{row['id']}_today"] = (
                f"{row['name']} today",
                row["today_count"],
                date,
            )
            result[f"activity_{row['id']}_7_days"] = (
                f"{row['name']} last 7 days",
                row["week_count"],
                week,
            )
    return result


class StatsSensor(CoordinatorEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:chart-box-outline"

    def __init__(self, coordinator, entry_id, key, name):
        super().__init__(coordinator)
        self.key = key
        self._attr_unique_id = f"{entry_id}_stats_{key}"
        self._attr_name = f"Vitality {name}"

    @property
    def native_value(self):
        value = self.coordinator.data[self.key][1]
        return value if isinstance(value, (int, float)) else None

    @property
    def extra_state_attributes(self):
        return self.coordinator.data[self.key][2]


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
