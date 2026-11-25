"""Read cached HA states and listen for Garmin source updates."""

import asyncio
import logging
import re
from datetime import UTC, datetime, timedelta

from homeassistant.const import EVENT_HOMEASSISTANT_STOP, EVENT_STATE_CHANGED
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.start import async_at_start

from .const import SIGNAL
from .garmin_data import (
    METRICS,
    WORKOUT_DEFAULTS,
    available,
    defaults,
    ingest,
    observation,
    preferences,
    save_preferences,
    workout,
)
from .validation import Invalid, clock, iso, key, number, only, text

_LOGGER = logging.getLogger(__name__)


class Garmin:
    def __init__(self, runtime):
        self.runtime = runtime
        self.hass = runtime.hass
        self.zone = runtime.zone
        self.registry = er.async_get(self.hass)
        self.config = {}
        self.status = {}
        self.seen = {}
        self.lock = asyncio.Lock()
        self.unsubscribers = []
        self.tasks = set()
        self.stopped = False
        self.subscribed_ids = set()

    async def start(self):
        self.config = await self.runtime.run(preferences, self.runtime.diary)
        self.capture(baseline=True)
        self.unsubscribers.extend(
            [
                self.hass.bus.async_listen(EVENT_STATE_CHANGED, self.changed),
                self.hass.bus.async_listen(EVENT_HOMEASSISTANT_STOP, self.stopping),
                async_at_start(self.hass, self.started),
                async_track_time_interval(
                    self.hass, self.periodic, timedelta(minutes=15)
                ),
            ]
        )

    async def close(self):
        if self.stopped:
            return
        self.stopped = True
        for unsubscribe in self.unsubscribers:
            unsubscribe()
        if self.tasks:
            await asyncio.gather(*tuple(self.tasks), return_exceptions=True)
        async with self.lock:
            pass

    async def stopping(self, _event):
        await self.close()

    @callback
    def started(self, _hass):
        self.schedule(self.capture(baseline=True))

    @callback
    def periodic(self, _now):
        self.schedule(self.capture())

    @callback
    def changed(self, event):
        entity_id = event.data["entity_id"]
        if entity_id not in self.subscribed_ids:
            row = self.registry.async_get(entity_id)
            if row is None or row.platform != "garmin_connect":
                return
        self.schedule(self.capture())

    @callback
    def schedule(self, snapshot):
        if self.stopped:
            return
        task = self.hass.async_create_task(
            self.sync_background(snapshot), "Vitality Garmin sync"
        )
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def sync_background(self, snapshot):
        try:
            await self.sync(snapshot)
        except HomeAssistantError:
            _LOGGER.warning("Vitality could not save Garmin observations")

    def discover(self, suffix):
        if not suffix:
            return None
        candidates = []
        for row in self.registry.entities.values():
            if (
                row.platform != "garmin_connect"
                or row.domain != "sensor"
                or row.disabled
            ):
                continue
            slug = re.sub(
                r"[^a-z0-9]+", "_", (row.original_name or "").casefold()
            ).strip("_")
            if (
                row.translation_key == suffix
                or row.unique_id.endswith(f"_{suffix}")
                or slug == suffix
                or row.entity_id.endswith(f"_{suffix}")
            ):
                candidates.append(row)
        return candidates[0] if len(candidates) == 1 else None

    def entity(self, binding, suffix):
        if binding.startswith("registry:"):
            return self.registry.async_get(binding[9:])
        if binding:
            return self.registry.async_get(binding)
        return self.discover(suffix)

    def binding(self, value):
        value = text(value, 160)
        if not value:
            return ""
        if not re.fullmatch(r"sensor\.[a-z0-9_]+", value):
            raise Invalid("Enter a sensor entity ID, or leave it blank for discovery.")
        row = self.registry.async_get(value)
        if row is None and self.hass.states.get(value) is None:
            raise Invalid("The selected sensor does not exist.")
        return f"registry:{row.id}" if row else value

    def source(self, binding, suffix):
        row = self.entity(binding, suffix)
        entity_id = (
            row.entity_id if row else binding if binding.startswith("sensor.") else ""
        )
        if entity_id:
            self.subscribed_ids.add(entity_id)
        return row, None if row and row.disabled else self.hass.states.get(entity_id)

    def metric_config(self, metric):
        return defaults(metric) | self.config.get("metrics", {}).get(metric, {})

    def workout_config(self):
        return WORKOUT_DEFAULTS | self.config.get("workouts", {})

    def capture(self, *, baseline=False):
        self.subscribed_ids = set()
        metrics = {}
        for metric in METRICS.keys() | self.config.get("metrics", {}).keys():
            mapping = self.metric_config(metric)
            row, state = self.source(mapping["entity"], mapping["auto_entity"])
            fresh = False
            if state is not None and mapping["enabled"]:
                identity = row.id if row else state.entity_id
                previous = self.seen.get(metric)
                marker = (identity, state.last_updated)
                if not baseline and previous and previous[0] == identity:
                    fresh = marker != previous
                if baseline or previous is None or previous[0] != identity:
                    self.seen[metric] = marker
            metrics[metric] = (mapping, state, fresh)
        config = self.workout_config()
        workout_sources = [
            self.source(config["list_source"], "last_activities"),
            self.source(config["latest_source"], "last_activity"),
        ]
        return self.config, metrics, config, workout_sources

    async def sync(self, snapshot=None, *, backfill=None):
        async with self.lock:
            if self.stopped:
                return None
            profile_config, metrics, config, workout_sources = (
                snapshot or self.capture()
            )
            if profile_config is not self.config:
                return None
            now = datetime.now(UTC)
            daily, samples, workouts, status = [], [], [], {}
            wake = None
            for metric in sorted(metrics, key=lambda k: k != "wake_time"):
                if backfill and metric != "wake_time":
                    continue
                mapping, state, fresh = metrics[metric]
                receipt = iso(state.last_updated) if state else None
                status[metric] = {
                    "availability": "missing" if state is None else "unavailable",
                    "source": "garmin",
                    "last_update": receipt,
                }
                if not mapping["enabled"]:
                    status[metric]["availability"] = "disabled"
                    continue
                if not available(state):
                    continue
                status[metric]["availability"] = "available"
                try:
                    observation_row = observation(
                        metric, mapping, state, wake, self.zone, fresh, now
                    )
                except Invalid as err:
                    if (
                        mapping["mode"] != "sample"
                        or not status[metric].get("last_update")
                        or not str(err).startswith("Waiting for")
                    ):
                        status[metric].update(availability="deferred", error=str(err))
                    continue
                if metric == "wake_time":
                    wake = (observation_row[3], receipt)
                if mapping["mode"] == "daily":
                    daily.append(observation_row)
                else:
                    samples.append(observation_row)
            errors, available_sources = 0, 0
            if config["enabled"]:
                # List first so the supplemental entity cannot erase complete list fields.
                for index, (row, state) in enumerate(workout_sources):
                    if not available(state):
                        continue
                    available_sources += 1
                    received = iso(state.last_updated)
                    raw = (
                        state.attributes.get(config["list_attribute"])
                        if index == 0
                        else [state.attributes]
                    )
                    if not isinstance(raw, (list, tuple)):
                        errors += 1
                        continue
                    profile = (
                        row.config_entry_id
                        if row and row.config_entry_id
                        else "configured_garmin"
                    )
                    for item in raw[:200]:
                        try:
                            parsed = workout(item, profile, received, config, now)
                            if backfill and not backfill[0] <= parsed[5] < backfill[1]:
                                continue
                            workouts.append(parsed)
                        except Invalid, ValueError, OverflowError:
                            errors += 1
            if backfill:
                await self.runtime.run(ingest, self.runtime.diary, [], [], workouts)
                async_dispatcher_send(self.hass, SIGNAL)
                return {
                    "records_seen": len({row[0] for row in workouts}),
                    "skipped": errors,
                }
            rejected = await self.runtime.run(
                ingest, self.runtime.diary, daily, samples, workouts
            )
            for metric, (mapping, state, fresh) in metrics.items():
                if not fresh:
                    continue
                row = self.entity(mapping["entity"], mapping["auto_entity"])
                identity = row.id if row else state.entity_id
                previous = self.seen.get(metric)
                if (
                    previous
                    and previous[0] == identity
                    and previous[1] < state.last_updated
                ):
                    self.seen[metric] = (identity, state.last_updated)
            for metric in rejected:
                status[metric].update(
                    availability="deferred",
                    error="An undated value matches a previous day.",
                )
            status["workouts"] = {
                "source": "garmin",
                "availability": (
                    "disabled"
                    if not config["enabled"]
                    else "available"
                    if available_sources
                    else "missing"
                ),
                "error": f"{errors} source records or lists could not be read."
                if errors
                else None,
            }
            self.status = status
            async_dispatcher_send(self.hass, SIGNAL)
            return {
                "records_seen": len({row[0] for row in workouts}),
                "skipped": errors,
            }

    def describe(self):
        mappings = {}
        for metric in sorted(METRICS.keys() | self.config.get("metrics", {}).keys()):
            mapping = self.metric_config(metric)
            row = self.entity(mapping["entity"], mapping["auto_entity"])
            entity_id = row.entity_id if row else mapping["entity"]
            mappings[metric] = {
                **mapping,
                "entity": entity_id if entity_id.startswith("sensor.") else "",
                "auto": not mapping["entity"],
                "status": self.status.get(metric, {}),
            }
        workouts = self.workout_config()
        for field, fallback in (
            ("list_source", "last_activities"),
            ("latest_source", "last_activity"),
        ):
            row = self.entity(workouts[field], fallback)
            workouts[f"{field}_resolved"] = (
                row.entity_id
                if row
                else workouts[field]
                if workouts[field].startswith("sensor.")
                else ""
            )
            workouts[field] = workouts[f"{field}_resolved"] if workouts[field] else ""
        return {
            "metrics": mappings,
            "workouts": workouts,
            "status": self.status.get("workouts", {}),
        }

    async def save_metric(self, data):
        only(
            data,
            "key",
            "entity",
            "enabled",
            "type",
            "unit",
            "mode",
            "date_policy",
            "attribute",
            "date_attribute",
            "time_attribute",
        )
        metric = key(data.get("key"))
        old = self.metric_config(metric)
        mapping = dict(old)
        mapping.update({name: value for name, value in data.items() if name != "key"})
        if "entity" in data:
            mapping["entity"] = self.binding(data["entity"])
        if (
            mapping["type"] not in ("numeric", "timestamp")
            or mapping["mode"] not in ("daily", "sample")
            or mapping["date_policy"]
            not in ("source", "changed", "wake", "bedtime", "sleep")
            or not isinstance(mapping["enabled"], bool)
        ):
            raise Invalid("Select a supported type, collection mode and date policy.")
        if metric in (
            "wake_time",
            "bedtime",
            "sleep_duration",
            "sleep_score",
            "body_battery",
        ):
            fixed = defaults(metric)
            if any(
                mapping[k] != fixed[k] for k in ("type", "mode", "date_policy", "unit")
            ):
                raise Invalid(
                    "The required Garmin metrics have fixed types, units and collection policies."
                )
        elif mapping["date_policy"] not in ("source", "changed"):
            raise Invalid(
                "Sleep pairing policies are reserved for the required sleep metrics."
            )
        for field in ("unit", "attribute", "date_attribute", "time_attribute"):
            mapping[field] = text(mapping[field], 32 if field == "unit" else 120)
        async with self.lock:
            metrics = {**self.config.get("metrics", {}), metric: mapping}
            if len(metrics.keys() | METRICS.keys()) > 64:
                raise Invalid("Use at most 64 scalar metric mappings.")
            await self.runtime.run(
                save_preferences, self.runtime.diary, "metrics", metrics
            )
            self.config = {**self.config, "metrics": metrics}
            self.seen.pop(metric, None)
        await self.sync()

    async def save_workouts(self, data):
        only(data, *WORKOUT_DEFAULTS)
        config = self.workout_config() | data
        for field in ("list_source", "latest_source"):
            if field in data:
                config[field] = self.binding(data[field])
        for field in ("late_threshold", "sleep_anchor"):
            clock(config[field])
        if (
            config["duration_unit"] not in ("s", "min", "ignore")
            or config["distance_unit"] not in ("m", "km", "ignore")
            or not isinstance(config["enabled"], bool)
        ):
            raise Invalid("Choose valid workout settings.")
        config["list_attribute"] = text(config["list_attribute"], required=True)
        config["battery_tolerance"] = number(
            config["battery_tolerance"], low=1, high=720
        )
        raw_types, raw_map = config["late_types"], config["type_map"]
        if (
            not isinstance(raw_map, dict)
            or not isinstance(raw_types, list)
            or len(raw_map) > 100
            or len(raw_types) > 100
        ):
            raise Invalid("Enter up to 100 workout types or mappings.")
        config["late_types"] = [
            text(value, required=True).casefold() for value in raw_types
        ]
        config["type_map"] = {
            text(source, required=True).casefold(): key(target)
            for source, target in raw_map.items()
        }
        async with self.lock:
            ids = {
                row["id"] for row in await self.runtime.run(self.runtime.diary.types)
            }
            if not set(config["type_map"].values()) <= ids:
                raise Invalid(
                    "Map workouts only to activity IDs in the Vitality catalogue."
                )
            await self.runtime.run(
                save_preferences, self.runtime.diary, "workouts", config
            )
            self.config = {**self.config, "workouts": config}
        await self.sync()
