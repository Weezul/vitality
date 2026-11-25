"""Validation shared by actions, storage and Garmin imports."""

import math
import re
from datetime import UTC, date, datetime, time, timedelta

from .const import KINDS, MAX_DAYS


class Invalid(ValueError):
    """Safe input error suitable for display."""


def text(value, limit=120, *, required=False):
    if not isinstance(value, str) or len(value) > limit or "\x00" in value:
        raise Invalid(f"Enter text of at most {limit} characters.")
    value = value.strip()
    if required and not value:
        raise Invalid("A value is required.")
    return value


def key(value):
    value = text(value, 64, required=True)
    if not re.fullmatch(r"[a-z][a-z0-9_]*", value):
        raise Invalid(
            "Use an ID starting with a letter and containing lowercase letters, digits or underscores."
        )
    return value


def number(value, *, low=None, high=None):
    if isinstance(value, bool):
        raise Invalid("Enter a valid number.")
    try:
        result = float(value)
    except ValueError, TypeError, OverflowError:
        raise Invalid("Enter a valid number.") from None
    if (
        not math.isfinite(result)
        or abs(result) > 1e12
        or (low is not None and result < low)
        or (high is not None and result > high)
    ):
        raise Invalid("The number is outside the allowed range.")
    return result


def score(value):
    result = number(value, low=1, high=10)
    if not result.is_integer():
        raise Invalid("Score must be a whole number from 1 to 10.")
    return int(result)


def kind(value):
    if value not in KINDS:
        raise Invalid("Select a valid check-in type.")
    return value


def iso(value):
    try:
        if isinstance(value, str):
            value = datetime.fromisoformat(text(value, 64, required=True))
        if not isinstance(value, datetime) or value.utcoffset() is None:
            raise ValueError
        return value.astimezone(UTC).isoformat(timespec="microseconds")
    except ValueError, OverflowError:
        raise Invalid("Use an ISO 8601 timestamp with a timezone offset.") from None


def now_iso():
    return iso(datetime.now(UTC))


def day(value):
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() == value and 1900 <= parsed.year < 9999:
            return parsed
    except TypeError, ValueError:
        pass
    raise Invalid("Use a calendar date in YYYY-MM-DD format.")


def bounds(start, end, zone):
    first, last = day(start), day(end)
    count = (last - first).days + 1
    if not 1 <= count <= MAX_DAYS:
        raise Invalid(f"Choose a date range of 1 to {MAX_DAYS} days.")
    after = last + timedelta(days=1)
    return (
        iso(datetime.combine(first, time.min, zone)),
        iso(datetime.combine(after, time.min, zone)),
    )


def local(utc, zone):
    return datetime.fromisoformat(utc).astimezone(zone)


def clock(value):
    try:
        if re.fullmatch(r"[0-9]{2}:[0-9]{2}", value):
            return time.fromisoformat(value)
    except TypeError, ValueError:
        pass
    raise Invalid("Use a clock time in HH:MM format.")


def only(data, *fields):
    if not isinstance(data, dict) or data.keys() - set(fields):
        raise Invalid("Unexpected fields in this request.")
