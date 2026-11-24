"""Exploratory paired-day analysis with explicit units and missing values."""

from statistics import StatisticsError, correlation, mean

from .queries import daily
from .validation import Invalid, clock, key, local, number, only, text

OUTCOMES = {
    "evening": "Evening score on day D",
    "next_morning": "Morning score on day D+1",
    "change": "Evening minus morning score on day D",
}


def clock_minutes(timestamp, zone, anchor):
    actual = local(timestamp, zone)
    return (
        actual.hour * 60 + actual.minute - (anchor.hour * 60 + anchor.minute)
    ) % 1440


def analyze(diary, zone, data):
    only(
        data,
        "start",
        "end",
        "activity_type",
        "category",
        "predictor",
        "outcome",
        "metric",
        "unit",
        "threshold",
        "anchor",
    )
    predictor, outcome = data.get("predictor", "count"), data.get("outcome", "evening")
    if (
        predictor
        not in ("count", "quantity", "workout_count", "late_workouts", "metric")
        or outcome not in OUTCOMES
    ):
        raise Invalid("Select a supported predictor and outcome.")
    metric = data.get("metric")
    if predictor == "metric":
        metric = text(metric, 70, required=True)
        segments = metric.split(".")
        key(segments[0])
        if len(segments) > 2 or (
            len(segments) == 2 and segments[1] not in ("first", "last")
        ):
            raise Invalid("Select a valid metric.")
    unit = text(data.get("unit", ""), 32)
    anchor = clock(data.get("anchor", "18:00"))
    grouping = data.get("threshold")
    if grouping is not None:
        grouping = number(grouping)
    elif predictor != "metric":
        grouping = 0
    daily_input = {
        k: data[k] for k in ("start", "end", "activity_type", "category") if k in data
    }
    rows = daily(diary, zone, daily_input)
    pairs = []
    for index, row in enumerate(rows):
        if predictor == "metric":
            entry = row["metrics"].get(metric)
            if not entry or entry["unit"] != unit:
                continue
            value = (
                clock_minutes(entry["value"], zone, anchor)
                if entry["value_type"] == "timestamp"
                else entry["value"]
            )
        elif predictor == "quantity":
            value = row["quantities"].get(unit, 0 if row["count"] == 0 else None)
        else:
            value = row[predictor]
        if outcome == "next_morning":
            score = rows[index + 1]["morning"] if index + 1 < len(rows) else None
        elif outcome == "change":
            score = (
                row["evening"] - row["morning"]
                if None not in (row["morning"], row["evening"])
                else None
            )
        else:
            score = row["evening"]
        if value is not None and score is not None:
            pairs.append((value, score))
    coefficient = None
    if len(pairs) >= 7:
        x, y = zip(*pairs)
        try:
            coefficient = correlation(x, y)
        except StatisticsError:
            pass
    groups = None
    if grouping is not None:
        lower = [score for value, score in pairs if value <= grouping]
        upper = [score for value, score in pairs if value > grouping]
        low_mean, high_mean = (
            mean(lower) if lower else None,
            mean(upper) if upper else None,
        )
        groups = {
            "threshold": grouping,
            "lower_n": len(lower),
            "upper_n": len(upper),
            "lower_mean": low_mean,
            "upper_mean": high_mean,
            "difference": high_mean - low_mean if upper and lower else None,
        }
    return {
        "start": data["start"],
        "end": data["end"],
        "outcome": OUTCOMES[outcome],
        "lag_days": int(outcome == "next_morning"),
        "n": len(pairs),
        "r": coefficient,
        "warning": len(pairs) < 30,
        "groups": groups,
    }
