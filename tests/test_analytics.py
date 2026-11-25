from datetime import date, timedelta

from pytest import approx

from custom_components.vitality.analytics import analyze, clock_minutes
from custom_components.vitality.validation import clock


def test_correlation_and_missing_paired_days(diary, zone):
    diary.save_type({"id": "coffee", "name": "Coffee", "unit": "cup"})
    start = date.fromisoformat("2026-11-01")
    for i in range(10):
        date_value = (start + timedelta(days=i)).isoformat()
        stamp = date_value + "T12:00:00+01:00"
        if i:
            diary.save_record(
                "events",
                {"activity_type": "coffee", "quantity": i, "occurred_at": stamp},
            )
        for kind, score in (("morning", 10 - i), ("evening", 1 + i)):
            if kind == "evening" and i == 6:
                continue
            diary.save_record(
                "checkins", {"kind": kind, "score": score, "occurred_at": stamp}
            )
    query = {
        "start": start.isoformat(),
        "end": "2026-11-10",
        "activity_type": "coffee",
        "predictor": "quantity",
        "unit": "cup",
    }
    same = analyze(diary, zone, query)
    assert same["n"] == 9 and same["warning"]
    assert same["r"] == approx(1)
    assert same["groups"]["lower_n"] == 1 and same["groups"]["upper_n"] == 8
    lagged = analyze(diary, zone, dict(query, outcome="next_morning"))
    assert lagged["n"] == 9 and lagged["r"] == approx(-1) and lagged["lag_days"] == 1
    assert analyze(diary, zone, dict(query, outcome="change"))["r"] == approx(1)
    assert analyze(diary, zone, dict(query, end="2026-11-05"))["r"] is None
    assert (
        analyze(diary, zone, dict(query, start="2026-11-02", predictor="count"))["r"]
        is None
    )


def test_bedtime_midnight_is_adjacent(zone):
    minutes = [
        clock_minutes(f"2026-11-{day}T{hour}:00+01:00", zone, clock("18:00"))
        for day, hour in (("23", "23:55"), ("24", "00:05"))
    ]
    assert minutes[1] - minutes[0] == 10


def test_rating_comparisons_average_ratings_and_respect_date_range(diary, zone):
    diary.save_type({"id": "coffee", "name": "Coffee"})
    diary.save_record(
        "events", {"activity_type": "coffee", "occurred_at": "2026-11-01T08:00:00Z"}
    )
    for stamp, score in (("01T09:00:00Z", 4), ("01T12:00:00Z", 8), ("03T12:00:00Z", 9)):
        for kind in ("mood", "energy"):
            diary.save_record(
                "checkins",
                {"kind": kind, "score": score, "occurred_at": "2026-11-" + stamp},
            )
    query = {"start": "2026-11-01", "end": "2026-11-03", "activity_type": "coffee"}
    same = analyze(diary, zone, dict(query, outcome="mood"))
    assert same["n"] == 2
    assert same["groups"]["upper_mean"] == 6
    assert same["groups"]["lower_mean"] == 9
    following = analyze(diary, zone, dict(query, outcome="next_mood"))
    assert following["lag_days"] == following["n"] == 1
    assert following["groups"]["lower_mean"] == 9
    assert (
        analyze(diary, zone, dict(query, outcome="energy"))["groups"] == same["groups"]
    )
    assert (
        analyze(diary, zone, dict(query, outcome="next_energy"))["groups"]
        == following["groups"]
    )
    assert (
        analyze(diary, zone, dict(query, outcome="next_mood", end="2026-11-02"))["n"]
        == 0
    )
