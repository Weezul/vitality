"""Pure Garmin observation parsing and persistence."""

from collections.abc import Mapping
from datetime import date, datetime, timedelta
from hashlib import sha256

from .storage import set_settings, settings
from .validation import Invalid, day, iso, local, number, only, text

METRICS = {
    "wake_time": ("wake_time", "timestamp", "", "daily", "wake"),
    "bedtime": ("bedtime", "timestamp", "", "daily", "bedtime"),
    "sleep_score": ("sleep_score", "numeric", "score", "daily", "sleep"),
    "sleep_duration": ("sleep_duration", "numeric", "min", "daily", "sleep"),
    "body_battery": ("body_battery", "numeric", "%", "sample", "source"),
    "body_battery_charged": (
        "body_battery_charged",
        "numeric",
        "points",
        "daily",
        "changed",
    ),
    "body_battery_drained": (
        "body_battery_drained",
        "numeric",
        "points",
        "daily",
        "changed",
    ),
    "body_battery_highest": (
        "body_battery_highest",
        "numeric",
        "%",
        "daily",
        "changed",
    ),
    "body_battery_lowest": ("body_battery_lowest", "numeric", "%", "daily", "changed"),
    "hrv_last_night_average": ("hrv_status", "numeric", "ms", "daily", "source"),
    "resting_heart_rate": ("resting_heart_rate", "numeric", "bpm", "daily", "changed"),
    "average_stress_level": (
        "average_stress_level",
        "numeric",
        "score",
        "daily",
        "changed",
    ),
    "max_stress_level": ("max_stress_level", "numeric", "score", "daily", "changed"),
    "morning_training_readiness": (
        "morning_training_readiness",
        "numeric",
        "%",
        "daily",
        "changed",
    ),
    "training_readiness": ("training_readiness", "numeric", "%", "daily", "source"),
}

WORKOUT_DEFAULTS = {
    "enabled": True,
    "list_source": "",
    "latest_source": "",
    "list_attribute": "last_activities",
    "duration_unit": "s",
    "distance_unit": "m",
    "late_threshold": "18:00",
    "late_types": [],
    "type_map": {},
    "battery_tolerance": 120,
    "sleep_anchor": "18:00",
}
FRESH_WINDOW = timedelta(hours=2)


def defaults(metric):
    entity, value_type, unit, mode, date_policy = METRICS.get(
        metric, ("", "numeric", "", "daily", "source")
    )
    return {
        "entity": "",
        "auto_entity": entity,
        "type": value_type,
        "unit": unit,
        "mode": mode,
        "date_policy": date_policy,
        "enabled": True,
        "attribute": "lastNightAvg" if metric == "hrv_last_night_average" else "",
        "date_attribute": "calendarDate"
        if metric in ("hrv_last_night_average", "training_readiness")
        else "",
        "time_attribute": "",
    }


def optional_number(value, **bounds):
    try:
        return number(value, **bounds)
    except Invalid:
        return None


def available(state):
    return state is not None and state.state not in ("unknown", "unavailable", "")


def stamp(state, mapping):
    field = mapping["time_attribute"]
    return iso(state.attributes.get(field) if field else state.last_updated)


def attribute_date(state, field):
    raw = state.attributes.get(field)
    return day(raw.isoformat() if type(raw) is date else raw).isoformat()


def source_date(state, mapping, value, wake, zone, fresh, now):
    attribute = mapping["date_attribute"]
    policy = mapping["date_policy"]
    if attribute and policy not in ("wake", "bedtime", "sleep"):
        return attribute_date(state, attribute), "source date"
    if policy == "wake":
        date = local(value, zone).date().isoformat()
        if attribute and attribute_date(state, attribute) != date:
            raise Invalid("Source date disagrees with the actual wake date.")
        return date, "actual wake date"
    if policy in ("bedtime", "sleep"):
        if policy == "sleep" and attribute:
            return attribute_date(state, attribute), "source date"
        if policy == "bedtime" and attribute:
            assigned = day(attribute_date(state, attribute))
            if (assigned - local(value, zone).date()).days not in (0, 1):
                raise Invalid("Actual bedtime does not fit the source wake date.")
            if wake and local(wake[0], zone).date() == assigned and value >= wake[0]:
                raise Invalid("Actual bedtime must precede actual wake time.")
            return assigned.isoformat(), "source date"
        if wake is None:
            raise Invalid("Waiting for an actual wake time.")
        wake_time, wake_received = wake
        date = local(wake_time, zone).date().isoformat()
        if policy == "bedtime":
            delta = datetime.fromisoformat(wake_time) - datetime.fromisoformat(value)
            if not timedelta(0) < delta <= timedelta(hours=20):
                raise Invalid("Actual bedtime does not fit the current wake time.")
            received = datetime.fromisoformat(stamp(state, mapping))
            wake_update = datetime.fromisoformat(wake_received)
            if (
                received < wake_update - FRESH_WINDOW
                and received > datetime.fromisoformat(value)
            ):
                raise Invalid("Bedtime and wake time have ambiguous freshness.")
            return date, "paired actual bedtime"
        received = datetime.fromisoformat(stamp(state, mapping))
        wake_update = datetime.fromisoformat(wake_received)
        if (
            received < datetime.fromisoformat(wake_time)
            or abs(received - wake_update) > FRESH_WINDOW
            or received.astimezone(zone).date().isoformat() != date
        ):
            raise Invalid(
                "Waiting for a sleep value updated near the actual wake time."
            )
        return date, "inferred from wake and update time"
    if mapping["time_attribute"] or mapping["type"] == "timestamp":
        when = stamp(state, mapping) if mapping["time_attribute"] else value
        return local(when, zone).date().isoformat(), "source timestamp"
    if policy == "changed" and fresh and now - state.last_updated <= FRESH_WINDOW:
        return local(
            iso(state.last_updated), zone
        ).date().isoformat(), "inferred from HA change"
    raise Invalid("No reliable source date is available.")


def observation(metric, mapping, state, wake, zone, fresh, now):
    if not available(state):
        raise Invalid("The mapped entity is unavailable.")
    field = mapping["attribute"]
    raw = state.attributes.get(field) if field else state.state
    if mapping["type"] == "timestamp":
        value = iso(raw)
    else:
        limits = (
            {"low": 0, "high": 100} if metric in ("body_battery", "sleep_score") else {}
        )
        if metric == "sleep_duration":
            limits = {"low": 0, "high": 1440}
        value = number(raw, **limits)
    if mapping["type"] == "timestamp" and datetime.fromisoformat(
        value
    ) > now + timedelta(minutes=5):
        raise Invalid("The metric timestamp is in the future.")
    observed = stamp(state, mapping)
    if datetime.fromisoformat(observed) > now + timedelta(minutes=5):
        raise Invalid("The observation timestamp is in the future.")
    unit = mapping["unit"] or (
        ""
        if mapping["type"] == "timestamp"
        else state.attributes.get("unit_of_measurement", "")
    )
    unit = text(unit or "", 32)
    if mapping["mode"] == "sample":
        if not mapping["time_attribute"] and (
            not fresh or now - state.last_updated > FRESH_WINDOW
        ):
            raise Invalid("Waiting for a fresh observation from Home Assistant.")
        provenance = (
            "source timestamp" if mapping["time_attribute"] else "HA receipt time"
        )
        return (
            metric,
            "garmin",
            value,
            unit,
            mapping["type"],
            observed,
            iso(now),
            provenance,
        )
    date, provenance = source_date(state, mapping, value, wake, zone, fresh, now)
    if day(date) > now.astimezone(zone).date():
        raise Invalid("The observation date is in the future.")
    return (
        date,
        metric,
        "garmin",
        value,
        unit,
        mapping["type"],
        observed,
        iso(now),
        provenance,
    )


def workout(raw, profile, received, config, now):
    if not isinstance(raw, Mapping):
        raise Invalid("An activity record is malformed.")
    external = raw.get("activityId")
    if type(external) not in (int, str):
        raise Invalid("An activity has no stable source ID.")
    external = text(str(external), 120, required=True)
    start = raw.get("startTime")
    try:
        occurred = iso(start)
    except Invalid:
        gmt = raw.get("startTimeGMT")
        if not isinstance(gmt, str):
            raise
        parsed = datetime.fromisoformat(gmt)
        occurred = iso(parsed if parsed.tzinfo is not None else gmt + "+00:00")
    if datetime.fromisoformat(occurred) > now + timedelta(minutes=5):
        raise Invalid("An activity start time is in the future.")
    activity_type = raw.get("activityType")
    if isinstance(activity_type, Mapping):
        activity_type = activity_type.get("typeKey")
    duration = optional_number(raw.get("duration"), low=0)
    distance = optional_number(raw.get("distance"), low=0)
    return (
        sha256(f"{profile}:{external}".encode()).hexdigest(),
        profile,
        external,
        text(raw["activityName"], 240)
        if isinstance(raw.get("activityName"), str)
        else None,
        text(activity_type, 120) if isinstance(activity_type, str) else None,
        occurred,
        duration / 60
        if duration is not None and config["duration_unit"] == "s"
        else duration
        if config["duration_unit"] == "min"
        else None,
        distance * 1000
        if distance is not None and config["distance_unit"] == "km"
        else distance
        if config["distance_unit"] == "m"
        else None,
        optional_number(raw.get("averageHR"), low=0),
        optional_number(raw.get("maxHR"), low=0),
        received,
        iso(now),
    )


def ingest(diary, daily, samples, workouts):
    """Upsert source facts without touching local overrides."""
    rejected = set()
    with diary.session(write=True) as db:
        for row in daily:
            date, metric, _, value, _, _, _, _, provenance = row
            if provenance in (
                "inferred from wake and update time",
                "paired actual bedtime",
                "inferred from HA change",
            ):
                previous = db.execute(
                    """SELECT value,local_date FROM daily_observations
                    WHERE metric_key=? AND source='garmin' AND local_date<?
                    ORDER BY local_date DESC LIMIT 1""",
                    (metric, date),
                ).fetchone()
                if previous and previous["value"] == value:
                    existing = db.execute(
                        "SELECT 1 FROM daily_observations WHERE metric_key=? AND local_date=? AND source='garmin'",
                        (metric, date),
                    ).fetchone()
                    if not existing:
                        rejected.add(metric)
                        continue
            db.execute(
                """INSERT INTO daily_observations VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(local_date,metric_key,source) DO UPDATE SET value=excluded.value,
                unit=excluded.unit,value_type=excluded.value_type,observed_at=excluded.observed_at,
                imported_at=excluded.imported_at,provenance=excluded.provenance
                WHERE excluded.observed_at>=daily_observations.observed_at
                AND (excluded.observed_at<>daily_observations.observed_at OR excluded.value<>daily_observations.value
                OR excluded.unit<>daily_observations.unit OR excluded.provenance<>daily_observations.provenance)""",
                row,
            )
        # Prefer the newest copy. The rolling list comes first when receipts are tied.
        deduplicated = {}
        for row in sorted(workouts, key=lambda value: value[10], reverse=True):
            previous = deduplicated.get(row[0], row)
            deduplicated[row[0]] = tuple(
                new if new is not None else old
                for new, old in zip(previous, row, strict=True)
            )
        db.executemany(
            """INSERT INTO metric_samples VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(metric_key,source,observed_at) DO UPDATE SET value=excluded.value,
            unit=excluded.unit,value_type=excluded.value_type,imported_at=excluded.imported_at
            WHERE excluded.value<>metric_samples.value OR excluded.unit<>metric_samples.unit""",
            samples,
        )
        db.executemany(
            """INSERT INTO workouts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(profile,external_id) DO UPDATE SET
              occurred_at=CASE WHEN excluded.received_at>=workouts.received_at THEN excluded.occurred_at ELSE workouts.occurred_at END,
              original_name=CASE WHEN excluded.received_at>=workouts.received_at THEN coalesce(excluded.original_name,workouts.original_name)
                ELSE coalesce(workouts.original_name,excluded.original_name) END,
              original_type=CASE WHEN excluded.received_at>=workouts.received_at THEN coalesce(excluded.original_type,workouts.original_type)
                ELSE coalesce(workouts.original_type,excluded.original_type) END,
              duration_minutes=CASE WHEN excluded.received_at>=workouts.received_at THEN coalesce(excluded.duration_minutes,workouts.duration_minutes)
                ELSE coalesce(workouts.duration_minutes,excluded.duration_minutes) END,
              distance_m=CASE WHEN excluded.received_at>=workouts.received_at THEN coalesce(excluded.distance_m,workouts.distance_m)
                ELSE coalesce(workouts.distance_m,excluded.distance_m) END,
              average_hr=CASE WHEN excluded.received_at>=workouts.received_at THEN coalesce(excluded.average_hr,workouts.average_hr)
                ELSE coalesce(workouts.average_hr,excluded.average_hr) END,
              max_hr=CASE WHEN excluded.received_at>=workouts.received_at THEN coalesce(excluded.max_hr,workouts.max_hr)
                ELSE coalesce(workouts.max_hr,excluded.max_hr) END,
              received_at=max(workouts.received_at,excluded.received_at), imported_at=excluded.imported_at
            WHERE excluded.received_at>workouts.received_at
               OR (excluded.received_at=workouts.received_at AND (
                   excluded.occurred_at<>workouts.occurred_at
                   OR coalesce(excluded.original_name,workouts.original_name) IS NOT workouts.original_name
                   OR coalesce(excluded.original_type,workouts.original_type) IS NOT workouts.original_type
                   OR coalesce(excluded.duration_minutes,workouts.duration_minutes) IS NOT workouts.duration_minutes
                   OR coalesce(excluded.distance_m,workouts.distance_m) IS NOT workouts.distance_m
                   OR coalesce(excluded.average_hr,workouts.average_hr) IS NOT workouts.average_hr
                   OR coalesce(excluded.max_hr,workouts.max_hr) IS NOT workouts.max_hr))
               OR (workouts.original_name IS NULL AND excluded.original_name IS NOT NULL)
               OR (workouts.original_type IS NULL AND excluded.original_type IS NOT NULL)
               OR (workouts.duration_minutes IS NULL AND excluded.duration_minutes IS NOT NULL)
               OR (workouts.distance_m IS NULL AND excluded.distance_m IS NOT NULL)
               OR (workouts.average_hr IS NULL AND excluded.average_hr IS NOT NULL)
               OR (workouts.max_hr IS NULL AND excluded.max_hr IS NOT NULL)""",
            deduplicated.values(),
        )
    return rejected


def preferences(diary):
    with diary.session() as db:
        return settings(db, "garmin", {})


def backfill_battery(diary, bounds, readings, now):
    """Persist validated HA history changes without replacing live observations."""
    if not isinstance(readings, list) or len(readings) > 1500:
        raise Invalid("Import up to 1,500 recorded Body Battery changes for one day.")
    rows = []
    for item in readings:
        only(item, "observed_at", "value")
        observed = iso(item.get("observed_at"))
        if not bounds[0] <= observed < bounds[1] or observed > iso(now):
            raise Invalid("A recorded change is outside the selected period.")
        rows.append(
            (
                "body_battery",
                "garmin",
                number(item.get("value"), low=0, high=100),
                "%",
                "numeric",
                observed,
                iso(now),
                "HA history state change",
            )
        )
    with diary.session(write=True) as db:
        cursor = db.executemany(
            "INSERT OR IGNORE INTO metric_samples VALUES(?,?,?,?,?,?,?,?)", rows
        )
        return {"inserted": cursor.rowcount}


def save_preferences(diary, section, value):
    with diary.session(write=True) as db:
        config = settings(db, "garmin", {})
        config[section] = value
        set_settings(db, "garmin", config)


def override(diary, data):
    only(
        data, "id", "excluded", "notes", "occurred_at", "duration_minutes", "manual_id"
    )
    identifier = text(data.get("id"), 64, required=True)
    with diary.session(write=True) as db:
        if not db.execute(
            "SELECT 1 FROM workouts WHERE id=?", (identifier,)
        ).fetchone():
            raise Invalid("That workout no longer exists.")
        previous = db.execute(
            "SELECT * FROM workout_overrides WHERE id=?", (identifier,)
        ).fetchone()
        merged = dict(previous) if previous else {}
        merged.update(data)
        excluded = merged.get("excluded", False)
        if "excluded" in data and not isinstance(excluded, bool):
            raise Invalid("Choose whether to exclude the workout.")
        occurred = merged.get("occurred_at")
        duration = merged.get("duration_minutes")
        manual = merged.get("manual_id")
        if manual:
            diary._record(db, "events", manual)
        db.execute(
            """INSERT INTO workout_overrides VALUES(?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET excluded=excluded.excluded,notes=excluded.notes,
            occurred_at=excluded.occurred_at,duration_minutes=excluded.duration_minutes,manual_id=excluded.manual_id""",
            (
                identifier,
                excluded,
                text(merged.get("notes", ""), 2000),
                iso(occurred) if occurred else None,
                number(duration, low=0) if duration is not None else None,
                manual or None,
            ),
        )
