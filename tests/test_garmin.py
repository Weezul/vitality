import json
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.vitality.garmin_data import (
    WORKOUT_DEFAULTS,
    backfill_battery,
    defaults,
    ingest,
    observation,
    override,
    save_preferences,
    workout,
)
from custom_components.vitality.queries import (
    daily,
    export,
    history,
    import_status,
    samples,
)
from custom_components.vitality.validation import Invalid, bounds, iso

DAY = {"start": "2026-11-24", "end": "2026-11-24"}
NOW = datetime.fromisoformat("2026-11-24T21:00:00+01:00")


def state(state_value, when, **attributes):
    return SimpleNamespace(
        state=state_value,
        last_updated=datetime.fromisoformat(when),
        attributes=attributes,
    )


def test_workout_dedup_enrichment_override_and_restore(diary, zone):
    fixture = json.loads(
        (Path(__file__).parent / "fixtures/garmin_workouts.json").read_text()
    )
    initial = iso("2026-11-24T19:00:00+01:00")
    later = iso("2026-11-24T20:00:00+01:00")
    rows = [
        workout(raw, "fixture", initial, WORKOUT_DEFAULTS, NOW)
        for raw in fixture["list"]
    ]
    latest = workout(fixture["latest"], "fixture", later, WORKOUT_DEFAULTS, NOW)
    diary.save_type({"id": "run", "name": "Running"})
    manual = diary.save_record(
        "events", {"activity_type": "run", "occurred_at": "2026-11-24T18:00:00+01:00"}
    )
    save_preferences(
        diary, "workouts", {"type_map": {"running": "run"}, "late_types": ["running"]}
    )
    ingest(diary, [], [], rows)
    assert daily(diary, zone, DAY)[0]["late_workouts"] == 1
    override(
        diary,
        {
            "id": latest[0],
            "excluded": True,
            "notes": "Local",
            "manual_id": manual,
            "occurred_at": "2026-11-24T18:05:00+01:00",
            "duration_minutes": 32,
        },
    )
    ingest(diary, [], [], [latest, *rows])
    ingest(diary, [], [], [*rows, latest])
    result = history(diary, zone, dict(DAY, source="garmin"))["records"]
    assert len(result) == 2
    run = result[0]
    assert run["occurred_at"] == iso("2026-11-24T17:05:00Z")
    assert (
        run["original_name"],
        run["name"],
        run["duration_minutes"],
        run["distance_m"],
    ) == ("Fixture evening run updated", "Running", 32, 5000)
    assert (run["notes"], run["manual_id"], run["excluded"]) == ("Local", manual, 1)
    assert daily(diary, zone, DAY)[0]["workout_count"] == 1
    override(diary, {"id": latest[0], "excluded": False})
    assert daily(diary, zone, DAY)[0]["workout_count"] == 2
    csv = export(diary, zone, dict(DAY, table="events"))["csv"]
    assert "5000.0" in csv and "polyline" not in csv and "startLatitude" not in csv
    assert (
        history(diary, zone, dict(DAY, name="evening", source="garmin"))["records"][0][
            "id"
        ]
        == latest[0]
    )


def test_workout_requires_stable_id_and_offset():
    with pytest.raises(Invalid, match="stable"):
        workout({"startTime": NOW}, "fixture", iso(NOW), WORKOUT_DEFAULTS, NOW)
    with pytest.raises(Invalid, match="offset"):
        workout(
            {"activityId": 1, "startTime": "2026-11-24T20:00:00"},
            "fixture",
            iso(NOW),
            WORKOUT_DEFAULTS,
            NOW,
        )


def test_sleep_staggered_late_corrected_and_no_reuse(diary, zone):
    now = datetime.fromisoformat("2026-11-24T12:00:00+01:00")
    wake_state = state("2026-11-24T07:02:00+01:00", "2026-11-24T07:20:00+01:00")
    wake_row = observation(
        "wake_time", defaults("wake_time"), wake_state, None, zone, False, now
    )
    wake = (wake_row[3], wake_row[6])
    bed = state("2026-11-23T23:18:00+01:00", "2026-11-24T07:08:00+01:00")
    score = state("82", "2026-11-24T08:00:00+01:00")
    duration = state("440", "2026-11-24T07:17:00+01:00")
    rows = [
        wake_row,
        *(
            observation(key, defaults(key), entity, wake, zone, False, now)
            for key, entity in (
                ("bedtime", bed),
                ("sleep_score", score),
                ("sleep_duration", duration),
            )
        ),
    ]
    ingest(diary, rows, [], [])
    current = daily(diary, zone, DAY)[0]["metrics"]
    assert current["bedtime"]["value"] == iso("2026-11-23T22:18:00Z")
    assert current["sleep_duration"]["value"] == 440
    assert current["sleep_score"]["value"] == 82
    assert current["wake_time"]["local_date"] == DAY["start"]
    later = datetime.fromisoformat("2026-11-25T08:30:00+01:00")
    new_wake = tuple(
        map(iso, ("2026-11-25T06:50:00+01:00", "2026-11-25T07:10:00+01:00"))
    )
    with pytest.raises(Invalid, match="Waiting"):
        observation(
            "sleep_score", defaults("sleep_score"), score, new_wake, zone, False, later
        )
    republished = state("82", "2026-11-25T07:11:00+01:00")
    duplicate = observation(
        "sleep_score",
        defaults("sleep_score"),
        republished,
        new_wake,
        zone,
        False,
        later,
    )
    assert ingest(diary, [duplicate], [], []) == {"sleep_score"}
    dated = state("84", "2026-11-25T07:40:00+01:00", calendarDate="2026-11-24")
    corrected = observation(
        "sleep_score",
        defaults("sleep_score") | {"date_attribute": "calendarDate"},
        dated,
        new_wake,
        zone,
        True,
        later,
    )
    ingest(diary, [corrected], [], [])
    assert daily(diary, zone, DAY)[0]["metrics"]["sleep_score"]["value"] == 84
    with pytest.raises(Invalid, match="unavailable"):
        observation(
            "sleep_score",
            defaults("sleep_score"),
            state("unavailable", "2026-11-25T07:41:00+01:00"),
            new_wake,
            zone,
            True,
            later,
        )


def test_samples_dedup_restart_daily_status_and_prior_only(diary, zone):
    mapping = defaults("body_battery")
    readings = [
        state(str(value), f"2026-11-24T{hour}:00:00+01:00")
        for hour, value in (("09", 80), ("10", 75), ("11", 68))
    ]
    now = datetime.fromisoformat("2026-11-24T11:02:00+01:00")
    with pytest.raises(Invalid, match="fresh"):
        observation("body_battery", mapping, readings[0], None, zone, False, now)
    rows = [
        observation("body_battery", mapping, item, None, zone, True, item.last_updated)
        for item in readings
    ]
    ingest(diary, [], rows, [])
    ingest(diary, [], rows, [])
    metrics = daily(diary, zone, DAY)[0]["metrics"]
    assert metrics["body_battery.first"]["value"] == 80
    assert metrics["body_battery.last"]["value"] == 68
    assert len(samples(diary, zone, DAY)["samples"]) == 3
    assert import_status(diary, zone)["body_battery"]["latest_day"] == DAY["start"]
    diary.save_record(
        "checkins",
        {"kind": "morning", "score": 8, "occurred_at": "2026-11-24T10:50:00+01:00"},
    )
    assert history(diary, zone, DAY)["records"][0]["prior_battery"]["value"] == 75
    save_preferences(diary, "workouts", {"battery_tolerance": 10})
    assert history(diary, zone, DAY)["records"][0]["prior_battery"] is None
    assert (
        "HA receipt time"
        in export(diary, zone, dict(DAY, table="metric_samples"))["csv"]
    )


def test_dated_custom_metric_and_zero(diary, zone):
    mapping = defaults("custom") | {
        "date_attribute": "calendarDate",
        "attribute": "value",
        "unit": "bpm",
    }
    stale = state(
        "valid", "2026-11-24T08:00:00+01:00", calendarDate=date(2026, 11, 23), value=0
    )
    row = observation("custom", mapping, stale, None, zone, False, NOW)
    ingest(diary, [row], [], [])
    result = daily(diary, zone, dict(DAY, start="2026-11-23"))
    assert result[0]["metrics"]["custom"]["value"] == 0
    assert "custom" not in result[1]["metrics"]


def test_backfill_preserves_live_sample_and_checks_range(diary, zone):
    recorded = state("58", "2026-11-24T13:00:00+01:00")
    live = observation(
        "body_battery",
        defaults("body_battery"),
        recorded,
        None,
        zone,
        True,
        recorded.last_updated,
    )
    ingest(diary, [], [live], [])
    period = bounds(DAY["start"], DAY["end"], zone)
    data = [
        {"value": 77, "observed_at": "2026-11-24T08:00:00+01:00"},
        {"value": 59, "observed_at": recorded.last_updated.isoformat()},
    ]
    assert backfill_battery(diary, period, data, NOW)["inserted"] == 1
    assert backfill_battery(diary, period, data, NOW)["inserted"] == 0
    readings = samples(diary, zone, DAY)["samples"]
    assert [row["provenance"] for row in readings] == [
        "HA history state change",
        "HA receipt time",
    ]
    assert [row["value"] for row in readings] == [77, 58]
    with pytest.raises(Invalid, match="outside"):
        backfill_battery(
            diary, period, [{"value": 70, "observed_at": "2026-11-23T08:00:00Z"}], NOW
        )


@pytest.mark.parametrize(
    ("day", "offset"), [("2026-03-29", "+02:00"), ("2026-10-25", "+01:00")]
)
def test_late_workout_dst_boundaries(day, offset, diary, zone):
    through = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
    rows = []
    for i, start in enumerate(
        (
            f"{day}T17:59:59{offset}",
            f"{day}T18:00:00{offset}",
            f"{through}T00:00:00{offset}",
        )
    ):
        rows.append(
            workout(
                {"activityId": i, "startTime": start},
                "fixture",
                iso(NOW),
                WORKOUT_DEFAULTS,
                NOW,
            )
        )
    ingest(diary, [], [], rows)
    first, after = daily(diary, zone, {"start": day, "end": through})
    assert (first["workout_count"], first["late_workouts"]) == (2, 1)
    assert (after["workout_count"], after["late_workouts"]) == (1, 0)
