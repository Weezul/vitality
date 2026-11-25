import sqlite3
from datetime import datetime, timedelta

import pytest

from custom_components.vitality.queries import daily, export, history, rating_readings
from custom_components.vitality.storage import MIGRATIONS, Diary
from custom_components.vitality.validation import Invalid, bounds

DAY = {"start": "2026-11-24", "end": "2026-11-24"}
STAMP = "2026-11-24T08:00:00+01:00"


def test_activity_quick_log_visibility_does_not_affect_logging(diary):
    coffee = {"id": "coffee", "name": "Coffee"}
    diary.save_type(coffee)
    assert diary.types()[0]["show_in_quick_log"] is True
    diary.save_type({**coffee, "show_in_quick_log": False})
    diary.save_type({**coffee, "name": "Espresso"})
    assert diary.types()[0]["show_in_quick_log"] is False
    assert diary.save_record("events", {"activity_type": "coffee"})
    with pytest.raises(Invalid, match="Quick Log"):
        diary.save_type({**coffee, "show_in_quick_log": "false"})


def test_types_and_quantities(diary, zone):
    coffee = {"id": "coffee", "name": "Coffee", "aliases": ["Espresso"], "unit": "cup"}
    diary.save_type(coffee)
    for quantity in (1, 1, 2):
        diary.save_record(
            "events",
            {"activity_type": " ESPRESSO ", "quantity": quantity, "occurred_at": STAMP},
        )
    diary.save_record(
        "events",
        {"activity_type": "Coffee", "quantity": 70, "unit": "ml", "occurred_at": STAMP},
    )
    diary.save_type(dict(coffee, name="Café", archived=True))
    with pytest.raises(Invalid, match="archived"):
        diary.save_record("events", {"activity_type": "CAFÉ"})
    with pytest.raises(Invalid, match="another"):
        diary.save_type({"id": "other", "name": "espresso"})
    with pytest.raises(Invalid, match="Unknown"):
        diary.save_record("events", {"activity_type": "Red Bull"})
    diary.save_type({"id": "red_bull", "name": "Red Bull"})
    row = daily(diary, zone, dict(DAY, activity_type="coffee"))[0]
    assert row["count"] == 4
    assert row["quantities"] == {"cup": 4, "ml": 70}


def test_checkins_edits_export_and_reopen(diary, zone):
    for kind, score in (("morning", 8), ("evening", 5), ("other", 3)):
        record = diary.save_record(
            "checkins", {"kind": kind, "score": score, "occurred_at": STAMP}
        )
    diary.save_record(
        "checkins",
        {"kind": "morning", "score": 9, "occurred_at": "2026-11-24T07:15:00Z"},
    )
    diary.save_record(
        "checkins",
        {"kind": "morning", "score": 7, "occurred_at": "2026-11-24T06:15:00Z"},
    )
    diary.save_record(
        "checkins",
        {"occurred_at": "2026-11-23T23:00:00Z", "notes": "=unsafe()"},
        record,
    )
    reopened = Diary(diary.path)
    reopened.initialize()
    row = daily(reopened, zone, DAY)[0]
    assert (row["morning"], row["evening"], row["other"]) == (9, 5, 3)
    assert "'=unsafe()" in export(reopened, zone, dict(DAY, table="checkins"))["csv"]
    assert history(reopened, zone, dict(DAY, limit=1))["next"] == 1
    reopened.delete_record("checkins", record)
    assert daily(reopened, zone, DAY)[0]["other"] is None


@pytest.mark.parametrize("bad", [True, 0, 1.5, 11, float("nan")])
def test_invalid_score(diary, bad):
    with pytest.raises(Invalid):
        diary.save_record("checkins", {"kind": "morning", "score": bad})


def test_mood_readings_keep_each_rating_and_use_local_day(diary, zone):
    for stamp, score in (
        ("2026-11-23T22:59:00Z", 10),
        ("2026-11-23T23:00:00Z", 3),
        ("2026-11-24T12:00:00Z", 8),
    ):
        diary.save_record(
            "checkins", {"kind": "mood", "score": score, "occurred_at": stamp}
        )
    ratings = rating_readings(diary, zone, DAY, "mood")["readings"]
    assert [row["score"] for row in ratings] == [3, 8]
    row = daily(diary, zone, DAY)[0]
    assert (row["mood"], row["mood_average"], row["mood_count"]) == (8, 5.5, 2)
    assert [row["score"] for row in history(diary, zone, DAY)["records"]] == [8, 3]


def test_energy_includes_legacy_and_multiple_new_ratings(diary, zone):
    for kind, day, hour, score in (
        ("morning", 24, 8, 3),
        ("energy", 24, 11, 8),
        ("mood", 24, 12, 5),
        ("energy", 24, 15, 6),
        ("evening", 24, 17, 7),
        ("energy", 25, 10, 9),
    ):
        diary.save_record(
            "checkins",
            {
                "kind": kind,
                "score": score,
                "occurred_at": f"2026-11-{day}T{hour:02}:00:00+01:00",
            },
        )
    ratings = rating_readings(diary, zone, {**DAY, "end": "2026-11-25"}, "energy")
    assert [row["score"] for row in ratings["readings"]] == [3, 8, 6, 7, 9]
    row = daily(diary, zone, DAY)[0]
    assert (row["energy"], row["energy_average"], row["energy_count"]) == (7, 6, 4)
    assert (row["morning"], row["evening"], row["mood"]) == (3, 7, 5)


@pytest.mark.parametrize(("date", "hours"), [("2026-03-29", 23), ("2026-10-25", 25)])
def test_swiss_dst(date, hours, zone):
    start, end = map(datetime.fromisoformat, bounds(date, date, zone))
    assert end - start == timedelta(hours=hours)


def test_reject_naive_timestamp(diary):
    with pytest.raises(Invalid, match="offset"):
        diary.save_record(
            "checkins",
            {"kind": "morning", "score": 5, "occurred_at": "2026-10-25T02:30"},
        )


def test_migrate_and_restore(tmp_path):
    original = tmp_path / "old.sqlite"
    restored = tmp_path / "restored.sqlite"
    with sqlite3.connect(original) as db:
        for sql in MIGRATIONS[0]:
            db.execute(sql)
        db.execute("PRAGMA user_version=1")
        db.execute(
            "INSERT INTO activity_types VALUES(?,?,?,?,?,?)",
            ("coffee", "Coffee", "", "", "[]", 0),
        )
        db.executemany(
            "INSERT INTO checkins VALUES(?,?,?,?,?,?,?)",
            [
                ("one", "morning", 80, STAMP, "", STAMP, STAMP),
                ("two", "evening", 45, STAMP, "", STAMP, STAMP),
                ("three", "other", 0, STAMP, "", STAMP, STAMP),
            ],
        )
        db.commit()
        with sqlite3.connect(restored) as backup:
            db.backup(backup)
    database = Diary(restored)
    database.initialize()
    assert database.types()[0]["show_in_quick_log"] is True
    assert database.latest("morning")["score"] == 8
    assert database.latest("evening")["score"] == 5
    assert database.latest("other")["score"] == 1
    with database.session() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
