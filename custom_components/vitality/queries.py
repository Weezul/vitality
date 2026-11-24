"""Bounded diary queries and CSV snapshots."""

import csv
import io
from datetime import datetime, timedelta

from .garmin_data import WORKOUT_DEFAULTS
from .storage import page, records, settings
from .validation import Invalid, bounds, clock, day, iso, key, local, only, text

WORKOUT_VIEW = """SELECT w.*, coalesce(o.occurred_at,w.occurred_at) AS effective_at,
    coalesce(o.duration_minutes,w.duration_minutes) AS effective_duration,
    coalesce(o.excluded,0) AS excluded, coalesce(o.notes,'') AS notes,
    o.occurred_at AS override_at, o.duration_minutes AS override_duration, o.manual_id,
    workout_type(w.original_type) AS activity_type_id,
    is_late(w.original_type,coalesce(o.occurred_at,w.occurred_at)) AS late
    FROM workouts w LEFT JOIN workout_overrides o ON o.id=w.id"""


def workout_functions(db, zone):
    config = WORKOUT_DEFAULTS | settings(db, "garmin", {}).get("workouts", {})
    mapping, eligible = config["type_map"], set(config["late_types"])
    threshold = clock(config["late_threshold"])
    db.create_function(
        "workout_type", 1, lambda value: mapping.get((value or "").casefold())
    )
    db.create_function(
        "is_late",
        2,
        lambda value, when: int(
            (not eligible or (value or "").casefold() in eligible)
            and local(when, zone).time() >= threshold
        ),
    )
    return config


def days_between(start, end):
    first = day(start)
    return [
        (first + timedelta(days=index)).isoformat()
        for index in range((day(end) - first).days + 1)
    ]


def range_args(zone, data, *extra):
    only(data, "start", "end", *extra)
    return bounds(data.get("start"), data.get("end"), zone)


def daily(diary, zone, data):
    lower, upper = range_args(zone, data, "activity_type", "category")
    conditions, params = filters(data)
    result = {
        date: {
            "date": date,
            "morning": None,
            "evening": None,
            "other": None,
            "count": 0,
            "quantities": {},
            "metrics": {},
            "workout_count": None,
            "late_workouts": None,
        }
        for date in days_between(data["start"], data["end"])
    }
    with diary.session() as db:
        db.create_function(
            "diary_date", 1, lambda value: local(value, zone).date().isoformat()
        )
        for row in db.execute(
            """SELECT local_day, kind, score FROM (
              SELECT diary_date(occurred_at) AS local_day, kind, score, row_number() OVER (
                PARTITION BY diary_date(occurred_at), kind ORDER BY occurred_at DESC, created_at DESC, id DESC
              ) AS rank FROM checkins WHERE occurred_at>=? AND occurred_at<?
            ) WHERE rank=1""",
            (lower, upper),
        ):
            result[row["local_day"]][row["kind"]] = row["score"]
        for row in db.execute(
            f"""SELECT diary_date(e.occurred_at) AS local_day, e.unit, count(*) AS count, sum(e.quantity) AS total
            FROM events e JOIN activity_types t ON e.activity_type_id=t.id
            WHERE e.occurred_at>=? AND e.occurred_at<? {conditions}
            GROUP BY local_day, e.unit""",
            (lower, upper, *params),
        ):
            item = result[row["local_day"]]
            item["count"] += row["count"]
            item["quantities"][row["unit"]] = row["total"]
        workout_functions(db, zone)
        for row in db.execute(
            f"""SELECT diary_date(effective_at) AS local_day,sum(excluded=0) AS count,
            sum(CASE WHEN excluded=0 THEN late ELSE 0 END) AS late
            FROM ({WORKOUT_VIEW}) WHERE effective_at>=? AND effective_at<? GROUP BY local_day""",
            (lower, upper),
        ):
            result[row["local_day"]].update(
                workout_count=row["count"], late_workouts=row["late"]
            )
        for row in db.execute(
            """SELECT * FROM daily_observations WHERE local_date>=? AND local_date<=?""",
            (data["start"], data["end"]),
        ):
            result[row["local_date"]]["metrics"][row["metric_key"]] = dict(row)
        for row in db.execute(
            """SELECT * FROM (
              SELECT *, diary_date(observed_at) AS local_day, row_number() OVER (
                PARTITION BY diary_date(observed_at),metric_key ORDER BY observed_at
              ) AS first, row_number() OVER (
                PARTITION BY diary_date(observed_at),metric_key ORDER BY observed_at DESC
              ) AS last FROM metric_samples WHERE observed_at>=? AND observed_at<?
            ) WHERE first=1 OR last=1""",
            (lower, upper),
        ):
            item = result[row["local_day"]]["metrics"]
            for name in ("first", "last"):
                if row[name] == 1:
                    item[f"{row['metric_key']}.{name}"] = dict(row) | {
                        "source": "derived",
                        "provenance": f"{name} observed sample · {row['provenance']}",
                    }
    return list(result.values())


def filters(data):
    clauses, params = [], []
    if value := data.get("activity_type"):
        clauses.append(" AND t.id=?")
        params.append(key(value))
    if value := data.get("category"):
        clauses.append(" AND t.category=?")
        params.append(text(value))
    if value := data.get("name"):
        clauses.append(
            " AND (instr(casefold(t.name), ?) > 0 OR instr(casefold(coalesce(e.original_name,'')), ?) > 0)"
        )
        params.extend([text(value).casefold()] * 2)
    return "".join(clauses), params


def history(diary, zone, data):
    lower, upper = range_args(
        zone, data, "offset", "limit", "activity_type", "category", "name", "source"
    )
    offset, limit = page(data.get("offset", 0), data.get("limit", 50))
    source = data.get("source", "all")
    if source not in ("all", "manual", "checkin", "garmin"):
        raise Invalid("Select a valid source.")
    conditions, params = filters(data)
    with diary.session() as db:
        workout_functions(db, zone)
        db.create_function(
            "casefold", 1, lambda value: value.casefold() if value else ""
        )
        result = records(
            db.execute(
                f"""SELECT * FROM (
              SELECT e.id,e.occurred_at,e.notes,e.activity_type_id,e.quantity,e.unit,e.duration_minutes,
                     t.name,t.category,'manual' AS source,NULL AS kind,NULL AS score,NULL AS distance_m,
                     NULL AS late,NULL AS excluded,NULL AS override_at,NULL AS override_duration,NULL AS manual_id,
                     NULL AS original_type,NULL AS original_name,NULL AS average_hr,NULL AS max_hr
              FROM (SELECT *, NULL AS original_name FROM events) e JOIN activity_types t ON e.activity_type_id=t.id
              WHERE e.occurred_at>=? AND e.occurred_at<? AND ? IN ('all','manual') {conditions}
              UNION ALL
              SELECT id,occurred_at,notes,NULL,NULL,NULL,NULL,NULL,NULL,'checkin',kind,score,
                     NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL FROM checkins
              WHERE occurred_at>=? AND occurred_at<? AND ? IN ('all','checkin') AND ?
              UNION ALL
              SELECT e.id,e.effective_at,e.notes,e.activity_type_id,NULL,NULL,e.effective_duration,
                     coalesce(t.name,e.original_name),t.category,'garmin',NULL,NULL,e.distance_m,e.late,
                     e.excluded,e.override_at,e.override_duration,e.manual_id,e.original_type,e.original_name,e.average_hr,e.max_hr
              FROM ({WORKOUT_VIEW}) e LEFT JOIN activity_types t ON t.id=e.activity_type_id
              WHERE e.effective_at>=? AND e.effective_at<? AND ? IN ('all','garmin') {conditions}
            ) ORDER BY occurred_at DESC,id DESC LIMIT ? OFFSET ?""",
                (
                    lower,
                    upper,
                    source,
                    *params,
                    lower,
                    upper,
                    source,
                    not conditions,
                    lower,
                    upper,
                    source,
                    *params,
                    limit + 1,
                    offset,
                ),
            )
        )
        tolerance = (
            settings(db, "garmin", {}).get("workouts", {}).get("battery_tolerance", 120)
        )
        for row in result[:limit]:
            if row["source"] != "checkin":
                continue
            earliest = iso(
                datetime.fromisoformat(row["occurred_at"])
                - timedelta(minutes=tolerance)
            )
            sample = db.execute(
                """SELECT value,observed_at,provenance FROM metric_samples WHERE metric_key='body_battery'
                AND observed_at>=? AND observed_at<=? ORDER BY observed_at DESC LIMIT 1""",
                (earliest, row["occurred_at"]),
            ).fetchone()
            row["prior_battery"] = dict(sample) if sample else None
    return {
        "records": result[:limit],
        "next": offset + limit if len(result) > limit else None,
    }


def csv_safe(value):
    if isinstance(value, str) and (
        value.lstrip().startswith(("=", "+", "-", "@"))
        or value.startswith(("\t", "\r", "\n"))
    ):
        return "'" + value
    return value


def export(diary, zone, data):
    lower, upper = range_args(zone, data, "offset", "limit", "table")
    offset, limit = page(data.get("offset", 0), data.get("limit", 200))
    table = data.get("table")
    if table not in ("events", "checkins", "daily_observations", "metric_samples"):
        raise Invalid("Select an export table.")
    with diary.session() as db:
        if table == "events":
            workout_functions(db, zone)
            query = f"""SELECT * FROM (
                SELECT id,activity_type_id,occurred_at,duration_minutes,notes,'manual' AS source,quantity,unit,
                    created_at,updated_at,NULL AS external_id,NULL AS original_name,NULL AS original_type,
                    NULL AS distance_m,NULL AS excluded,NULL AS manual_id,NULL AS source_at,NULL AS source_duration,
                    NULL AS average_hr,NULL AS max_hr,NULL AS late,NULL AS profile
                FROM events
                UNION ALL
                SELECT id,activity_type_id,effective_at,effective_duration,notes,'garmin',NULL,NULL,
                    imported_at,received_at,external_id,original_name,original_type,distance_m,excluded,manual_id,
                    occurred_at,duration_minutes,average_hr,max_hr,late,profile FROM ({WORKOUT_VIEW})
                ) WHERE occurred_at>=? AND occurred_at<? ORDER BY occurred_at,id"""
        elif table == "daily_observations":
            query = "SELECT * FROM daily_observations WHERE local_date>=? AND local_date<? ORDER BY local_date,metric_key,source"
            lower = data["start"]
            upper = (day(data["end"]) + timedelta(days=1)).isoformat()
        elif table == "metric_samples":
            query = "SELECT * FROM metric_samples WHERE observed_at>=? AND observed_at<? ORDER BY observed_at,metric_key,source"
        else:
            query = "SELECT * FROM checkins WHERE occurred_at>=? AND occurred_at<? ORDER BY occurred_at,id"
        cur = db.execute(f"{query} LIMIT ? OFFSET ?", (lower, upper, limit + 1, offset))
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer)
        writer.writerow([field[0] for field in cur.description])
        rows = cur.fetchall()
        writer.writerows([csv_safe(value) for value in row] for row in rows[:limit])
    return {
        "csv": buffer.getvalue(),
        "next": offset + limit if len(rows) > limit else None,
    }


def samples(diary, zone, data):
    lower, upper = range_args(zone, data, "metric")
    if data["start"] != data["end"]:
        raise Invalid("Choose one local date for intraday samples.")
    metric = key(data.get("metric", "body_battery"))
    with diary.session() as db:
        rows = records(
            db.execute(
                """SELECT * FROM metric_samples WHERE metric_key=? AND observed_at>=? AND observed_at<?
            ORDER BY observed_at LIMIT 1501""",
                (metric, lower, upper),
            )
        )
    return {
        "samples": rows[:1500],
        "truncated": len(rows) > 1500,
        "bounds": [lower, upper],
    }


def import_status(diary, zone):
    with diary.session() as db:
        latest = records(
            db.execute(
                """SELECT metric_key,max(imported_at) AS last_import,max(observation_day) AS latest_day,
               max(observed_at) AS latest_timestamp FROM (
              SELECT metric_key,imported_at,local_date AS observation_day, NULL AS observed_at FROM daily_observations
              UNION ALL
              SELECT metric_key,imported_at,NULL,observed_at FROM metric_samples
              UNION ALL
              SELECT 'workouts',imported_at,NULL,occurred_at FROM workouts
            ) GROUP BY metric_key"""
            )
        )
    for row in latest:
        if row["latest_timestamp"]:
            sample_day = local(row["latest_timestamp"], zone).date().isoformat()
            row["latest_day"] = max(row["latest_day"] or "", sample_day)
    return {row["metric_key"]: row for row in latest}
