"""SQLite diary. All public database methods run off the HA event loop."""

import json
import sqlite3
from contextlib import contextmanager
from threading import RLock
from uuid import uuid4

from .const import MAX_PAGE
from .validation import Invalid, iso, key, kind, now_iso, number, only, score, text

MIGRATIONS = (
    (
        """CREATE TABLE activity_types (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL,
            unit TEXT NOT NULL, aliases TEXT NOT NULL, archived INTEGER NOT NULL
        )""",
        """CREATE TABLE checkins (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('morning','evening','other')),
            score INTEGER NOT NULL CHECK(score BETWEEN 0 AND 100), occurred_at TEXT NOT NULL,
            notes TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""",
        "CREATE INDEX checkins_time ON checkins(occurred_at, id)",
        """CREATE TABLE events (
            id TEXT PRIMARY KEY, activity_type_id TEXT NOT NULL REFERENCES activity_types(id),
            occurred_at TEXT NOT NULL, quantity REAL NOT NULL CHECK(quantity > 0),
            unit TEXT NOT NULL, duration_minutes REAL, notes TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""",
        "CREATE INDEX events_time ON events(occurred_at, id)",
        "CREATE INDEX events_type ON events(activity_type_id, occurred_at)",
        "CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    ),
    (
        """CREATE TABLE daily_observations (
            local_date TEXT NOT NULL, metric_key TEXT NOT NULL, source TEXT NOT NULL,
            value NOT NULL, unit TEXT NOT NULL, value_type TEXT NOT NULL,
            observed_at TEXT NOT NULL, imported_at TEXT NOT NULL, provenance TEXT NOT NULL,
            PRIMARY KEY(local_date, metric_key, source)
        )""",
        """CREATE TABLE metric_samples (
            metric_key TEXT NOT NULL, source TEXT NOT NULL, value NOT NULL,
            unit TEXT NOT NULL, value_type TEXT NOT NULL, observed_at TEXT NOT NULL,
            imported_at TEXT NOT NULL, provenance TEXT NOT NULL,
            PRIMARY KEY(metric_key, source, observed_at)
        )""",
        "CREATE INDEX sample_time ON metric_samples(observed_at, metric_key)",
        """CREATE TABLE workouts (
            id TEXT PRIMARY KEY, profile TEXT NOT NULL, external_id TEXT NOT NULL,
            original_name TEXT, original_type TEXT, occurred_at TEXT NOT NULL,
            duration_minutes REAL, distance_m REAL, average_hr REAL, max_hr REAL,
            received_at TEXT NOT NULL, imported_at TEXT NOT NULL,
            UNIQUE(profile, external_id)
        )""",
        "CREATE INDEX workout_time ON workouts(occurred_at, id)",
        """CREATE TABLE workout_overrides (
            id TEXT PRIMARY KEY REFERENCES workouts(id), excluded INTEGER NOT NULL DEFAULT 0,
            notes TEXT NOT NULL DEFAULT '', occurred_at TEXT, duration_minutes REAL,
            manual_id TEXT REFERENCES events(id) ON DELETE SET NULL
        )""",
    ),
    (
        "ALTER TABLE checkins RENAME TO checkins_legacy",
        """CREATE TABLE checkins (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('morning','evening','other')),
            score INTEGER NOT NULL CHECK(score BETWEEN 1 AND 10), occurred_at TEXT NOT NULL,
            notes TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""",
        """INSERT INTO checkins
            SELECT id, kind, max(1, (score + 5) / 10), occurred_at, notes, created_at, updated_at
            FROM checkins_legacy""",
        "DROP TABLE checkins_legacy",
        "CREATE INDEX checkins_time ON checkins(occurred_at, id)",
    ),
    (
        "ALTER TABLE checkins RENAME TO checkins_before_mood",
        """CREATE TABLE checkins (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('morning','evening','other','mood')),
            score INTEGER NOT NULL CHECK(score BETWEEN 1 AND 10), occurred_at TEXT NOT NULL,
            notes TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""",
        "INSERT INTO checkins SELECT * FROM checkins_before_mood",
        "DROP TABLE checkins_before_mood",
        "CREATE INDEX checkins_time ON checkins(occurred_at, id)",
    ),
    (
        "ALTER TABLE checkins RENAME TO checkins_before_energy",
        """CREATE TABLE checkins (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('morning','evening','other','mood','energy')),
            score INTEGER NOT NULL CHECK(score BETWEEN 1 AND 10), occurred_at TEXT NOT NULL,
            notes TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""",
        "INSERT INTO checkins SELECT * FROM checkins_before_energy",
        "DROP TABLE checkins_before_energy",
        "CREATE INDEX checkins_time ON checkins(occurred_at, id)",
    ),
    (
        """ALTER TABLE activity_types ADD COLUMN show_in_quick_log INTEGER NOT NULL
           DEFAULT 1 CHECK(show_in_quick_log IN (0, 1))""",
    ),
)


def records(cursor):
    return [dict(row) for row in cursor]


def catalogue(db):
    result = records(
        db.execute("SELECT * FROM activity_types ORDER BY name COLLATE NOCASE, id")
    )
    for row in result:
        row["aliases"] = json.loads(row["aliases"])
        row["archived"] = bool(row["archived"])
        row["show_in_quick_log"] = bool(row["show_in_quick_log"])
    return result


def resolve(db, value, current=None):
    token = text(value, required=True).casefold()
    for row in catalogue(db):
        labels = [row["id"], row["name"], *row["aliases"]]
        if token in {label.casefold() for label in labels}:
            if row["archived"] and row["id"] != current:
                raise Invalid("That activity type is archived.")
            return row
    raise Invalid("Unknown activity type. Add it to the activity catalogue first.")


def settings(db, name, default):
    row = db.execute("SELECT value FROM settings WHERE key = ?", (name,)).fetchone()
    return json.loads(row[0]) if row else default


def set_settings(db, name, value):
    db.execute(
        "INSERT INTO settings VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (name, json.dumps(value)),
    )


class Diary:
    """Short connections with process-level serialization and transactional writes."""

    def __init__(self, path):
        self.path = path
        self._lock = RLock()

    @contextmanager
    def session(self, *, write=False):
        with self._lock:
            db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
            db.row_factory = sqlite3.Row
            try:
                db.execute("PRAGMA foreign_keys=ON")
                db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise
            finally:
                db.close()

    def initialize(self):
        with self.session(write=True) as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > len(MIGRATIONS):
                raise Invalid(
                    "The Vitality database requires a newer integration version."
                )
            for index in range(version, len(MIGRATIONS)):
                for statement in MIGRATIONS[index]:
                    db.execute(statement)
                db.execute(f"PRAGMA user_version={index + 1}")

    def types(self):
        with self.session() as db:
            recent = dict(
                db.execute(
                    "SELECT activity_type_id,max(occurred_at) FROM events GROUP BY activity_type_id"
                )
            )
            return [row | {"recent_at": recent.get(row["id"])} for row in catalogue(db)]

    def save_type(self, data):
        only(
            data,
            "id",
            "name",
            "category",
            "unit",
            "aliases",
            "archived",
            "create_only",
            "show_in_quick_log",
        )
        name = text(data.get("name"), required=True)
        type_id = key(data.get("id"))
        aliases = data.get("aliases", [])
        archived = data.get("archived", False)
        create_only = data.get("create_only", False)
        show_in_quick_log = data.get("show_in_quick_log")
        if "show_in_quick_log" in data and not isinstance(show_in_quick_log, bool):
            raise Invalid("Choose whether to show the activity in Quick Log.")
        if (
            not isinstance(aliases, list)
            or len(aliases) > 20
            or not isinstance(archived, bool)
            or not isinstance(create_only, bool)
        ):
            raise Invalid("Use at most 20 aliases and a valid archive setting.")
        aliases = [text(alias, required=True) for alias in aliases]
        tokens = {value.casefold() for value in [type_id, name, *aliases]}
        row = (
            type_id,
            name,
            text(data.get("category", "")),
            text(data.get("unit", ""), 32),
            json.dumps(aliases),
            archived,
        )
        with self.session(write=True) as db:
            existing = catalogue(db)
            if create_only and any(item["id"] == type_id for item in existing):
                raise Invalid(
                    "That stable ID already exists. Select the type to edit it."
                )
            if len(existing) >= 250 and not any(
                item["id"] == type_id for item in existing
            ):
                raise Invalid("The activity catalogue supports up to 250 types.")
            for item in existing:
                if item["id"] != type_id and tokens.intersection(
                    value.casefold()
                    for value in [item["id"], item["name"], *item["aliases"]]
                ):
                    raise Invalid(
                        "The ID, name or alias already identifies another activity."
                    )
            db.execute(
                """INSERT INTO activity_types
                (id,name,category,unit,aliases,archived,show_in_quick_log)
                VALUES(?,?,?,?,?,?,coalesce(?,1)) ON CONFLICT(id) DO UPDATE SET
                name=excluded.name, category=excluded.category, unit=excluded.unit,
                aliases=excluded.aliases, archived=excluded.archived,
                show_in_quick_log=coalesce(?,activity_types.show_in_quick_log)""",
                (*row, show_in_quick_log, show_in_quick_log),
            )
        return type_id

    def save_record(self, table, data, record_id=None):
        if table not in ("checkins", "events"):
            raise Invalid("Unknown record type.")
        fields = (
            ("kind", "score")
            if table == "checkins"
            else ("activity_type", "quantity", "unit", "duration_minutes")
        )
        only(data, *fields, "occurred_at", "notes")
        now = now_iso()
        with self.session(write=True) as db:
            old = {}
            if record_id is not None:
                old = self._record(db, table, record_id)
            occurred = iso(data.get("occurred_at", old.get("occurred_at", now)))
            notes = text(data.get("notes", old.get("notes", "")), 2000)
            if table == "checkins":
                specific = {
                    "kind": kind(data.get("kind", old.get("kind"))),
                    "score": score(data.get("score", old.get("score"))),
                }
            else:
                activity = resolve(
                    db,
                    data.get("activity_type", old.get("activity_type_id")),
                    old.get("activity_type_id"),
                )
                duration = data.get("duration_minutes", old.get("duration_minutes"))
                quantity = number(data.get("quantity", old.get("quantity", 1)))
                if quantity <= 0:
                    raise Invalid("Quantity must be positive.")
                default_unit = (
                    old["unit"]
                    if old.get("activity_type_id") == activity["id"]
                    else activity["unit"]
                )
                specific = {
                    "activity_type_id": activity["id"],
                    "quantity": quantity,
                    "unit": text(data.get("unit", default_unit), 32),
                    "duration_minutes": number(duration, low=0)
                    if duration is not None
                    else None,
                }
            values = dict(specific, occurred_at=occurred, notes=notes, updated_at=now)
            if record_id is None:
                record_id = uuid4().hex
                values.update(id=record_id, created_at=now)
                db.execute(
                    f"INSERT INTO {table} ({','.join(values)}) VALUES ({','.join('?' for _ in values)})",
                    tuple(values.values()),
                )
            else:
                db.execute(
                    f"UPDATE {table} SET {','.join(f'{col}=?' for col in values)} WHERE id=?",
                    (*values.values(), record_id),
                )
        return record_id

    @staticmethod
    def _record(db, table, record_id):
        record_id = text(record_id, 64, required=True)
        row = db.execute(f"SELECT * FROM {table} WHERE id=?", (record_id,)).fetchone()
        if row is None:
            raise Invalid("That record no longer exists.")
        return dict(row)

    def delete_record(self, table, record_id):
        if table not in ("checkins", "events"):
            raise Invalid("Unknown record type.")
        with self.session(write=True) as db:
            self._record(db, table, record_id)
            db.execute(f"DELETE FROM {table} WHERE id=?", (record_id,))

    def latest(self, kind_value):
        with self.session() as db:
            row = db.execute(
                """SELECT score, occurred_at FROM checkins WHERE kind=?
                ORDER BY occurred_at DESC, created_at DESC, id DESC LIMIT 1""",
                (kind(kind_value),),
            ).fetchone()
            return dict(row) if row else None


def page(offset, limit):
    if (
        type(offset) is not int
        or type(limit) is not int
        or not 0 <= offset <= 1_000_000
        or not 1 <= limit <= MAX_PAGE
    ):
        raise Invalid(f"Use a valid page offset and a page size of 1 to {MAX_PAGE}.")
    return offset, limit
