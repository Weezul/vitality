import sqlite3
from datetime import datetime, timedelta

import pytest

from custom_components.vitality.queries import daily, export, history
from custom_components.vitality.storage import MIGRATIONS, Diary
from custom_components.vitality.validation import Invalid, bounds

DAY = {"start": "2026-11-24", "end": "2026-11-24"}
STAMP = "2026-11-24T08:00:00+01:00"


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
    for kind, score in (("morning", 80), ("evening", 45), ("other", 25)):
        record = diary.save_record(
            "checkins", {"kind": kind, "score": score, "occurred_at": STAMP}
        )
    diary.save_record(
        "checkins",
        {"kind": "morning", "score": 81, "occurred_at": "2026-11-24T07:15:00Z"},
    )
    diary.save_record(
        "checkins",
        {"kind": "morning", "score": 79, "occurred_at": "2026-11-24T06:15:00Z"},
    )
    diary.save_record(
        "checkins",
        {"occurred_at": "2026-11-23T23:00:00Z", "notes": "=unsafe()"},
        record,
    )
    reopened = Diary(diary.path)
    reopened.initialize()
    row = daily(reopened, zone, DAY)[0]
    assert (row["morning"], row["evening"], row["other"]) == (81, 45, 25)
    assert "'=unsafe()" in export(reopened, zone, dict(DAY, table="checkins"))["csv"]
    assert history(reopened, zone, dict(DAY, limit=1))["next"] == 1
    reopened.delete_record("checkins", record)
    assert daily(reopened, zone, DAY)[0]["other"] is None


@pytest.mark.parametrize("bad", [True, -1, 1.5, 101, float("nan")])
def test_invalid_score(diary, bad):
    with pytest.raises(Invalid):
        diary.save_record("checkins", {"kind": "morning", "score": bad})


@pytest.mark.parametrize(("date", "hours"), [("2026-03-29", 23), ("2026-10-25", 25)])
def test_swiss_dst(date, hours, zone):
    start, end = map(datetime.fromisoformat, bounds(date, date, zone))
    assert end - start == timedelta(hours=hours)


def test_reject_naive_timestamp(diary):
    with pytest.raises(Invalid, match="offset"):
        diary.save_record(
            "checkins",
            {"kind": "morning", "score": 50, "occurred_at": "2026-10-25T02:30"},
        )


def test_migrate_and_restore(tmp_path):
    original = tmp_path / "old.sqlite"
    restored = tmp_path / "restored.sqlite"
    with sqlite3.connect(original) as db:
        for sql in MIGRATIONS[0]:
            db.execute(sql)
        db.execute("PRAGMA user_version=1")
        db.execute(
            "INSERT INTO checkins VALUES(?,?,?,?,?,?,?)",
            ("one", "morning", 80, STAMP, "", STAMP, STAMP),
        )
        db.commit()
        with sqlite3.connect(restored) as backup:
            db.backup(backup)
    database = Diary(restored)
    database.initialize()
    assert database.latest("morning")["score"] == 80
    with database.session() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
