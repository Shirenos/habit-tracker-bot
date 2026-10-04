import sqlite3
from datetime import date

import pytest

from habit_bot.db import SCHEMA_VERSION, Database


async def test_add_and_list_habits(db):
    h = await db.add_habit(1, "Read")
    assert h is not None and h.id > 0
    await db.add_habit(1, "Run")
    await db.add_habit(2, "Other user")
    assert [x.name for x in await db.list_habits(1)] == ["Read", "Run"]


async def test_duplicate_name_per_user_rejected(db):
    assert await db.add_habit(1, "Read") is not None
    assert await db.add_habit(1, "Read") is None
    assert await db.add_habit(2, "Read") is not None


async def test_get_and_delete_are_scoped_to_owner(db):
    h = await db.add_habit(1, "Read")
    assert await db.get_habit(2, h.id) is None
    assert await db.delete_habit(2, h.id) is False
    assert await db.delete_habit(1, h.id) is True
    assert await db.list_habits(1) == []


async def test_checkins_idempotent(db):
    h = await db.add_habit(1, "Read")
    day = date(2026, 10, 3)
    assert await db.add_checkin(h.id, day) is True
    assert await db.add_checkin(h.id, day) is False
    assert await db.get_checkin_days(h.id) == {day}


async def test_delete_cascades_checkins(db):
    h = await db.add_habit(1, "Read")
    await db.add_checkin(h.id, date(2026, 10, 3))
    await db.delete_habit(1, h.id)
    async with db.conn.execute("SELECT COUNT(*) FROM checkins") as cur:
        assert (await cur.fetchone())[0] == 0


async def test_reminder_upsert_and_remove(db):
    await db.set_reminder(1, 100, "09:00")
    await db.set_reminder(1, 100, "21:30")
    reminders = await db.list_reminders()
    assert len(reminders) == 1 and reminders[0].time == "21:30"
    assert await db.remove_reminder(1) is True
    assert await db.remove_reminder(1) is False


async def test_data_persists_on_disk(tmp_path):
    path = tmp_path / "nested" / "test.db"
    first = Database(path)
    await first.connect()
    await first.add_habit(1, "Read")
    await first.close()

    second = Database(path)
    await second.connect()
    assert [h.name for h in await second.list_habits(1)] == ["Read"]
    await second.close()


async def test_using_closed_db_raises():
    with pytest.raises(RuntimeError):
        await Database(":memory:").list_habits(1)


async def test_get_reminder(db):
    assert await db.get_reminder(1) is None
    await db.set_reminder(1, 100, "08:00")
    reminder = await db.get_reminder(1)
    assert (reminder.chat_id, reminder.time) == (100, "08:00")
    assert await db.get_reminder(2) is None


# --- case-insensitive names, schema versioning and migration -----------------------------------

LEGACY_SCHEMA = """
CREATE TABLE habits (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    name       TEXT    NOT NULL,
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (user_id, name)
);
CREATE INDEX idx_habits_user ON habits (user_id);
CREATE TABLE checkins (
    habit_id INTEGER NOT NULL REFERENCES habits (id) ON DELETE CASCADE,
    day      TEXT    NOT NULL,
    PRIMARY KEY (habit_id, day)
);
CREATE TABLE reminders (
    user_id INTEGER PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    time    TEXT    NOT NULL
);
"""


def make_legacy_db(path):
    """An old-schema (user_version 0, no name_key) database with tricky data."""
    con = sqlite3.connect(path)
    con.executescript(LEGACY_SCHEMA)
    habits = [
        (1, 1, "Read", "2026-01-01 10:00:00"),
        (2, 1, "read", "2026-01-02 10:00:00"),  # collides with "Read" once case is ignored
        (3, 1, "Пить воду", "2026-01-03 10:00:00"),
        (4, 1, "ПИТЬ ВОДУ", "2026-01-04 10:00:00"),  # Cyrillic duplicate
        (5, 2, "Read", "2026-01-05 10:00:00"),  # same name, another user: fine
        (6, 1, "READ", "2026-01-06 10:00:00"),  # third duplicate
        (7, 1, "temp", "2026-01-07 10:00:00"),  # deleted below: AUTOINCREMENT must not reuse 7
    ]
    con.executemany(
        "INSERT INTO habits (id, user_id, name, created_at) VALUES (?, ?, ?, ?)", habits
    )
    con.executemany(
        "INSERT INTO checkins (habit_id, day) VALUES (?, ?)",
        [
            (1, "2026-10-01"),
            (1, "2026-10-02"),
            (2, "2026-10-01"),
            (4, "2026-10-03"),
            (5, "2026-10-01"),
        ],
    )
    con.execute("INSERT INTO reminders VALUES (1, 100, '21:30')")
    con.execute("DELETE FROM habits WHERE id = 7")
    con.commit()
    con.close()


def user_version(path):
    con = sqlite3.connect(path)
    try:
        return con.execute("PRAGMA user_version").fetchone()[0]
    finally:
        con.close()


async def test_names_are_unique_ignoring_case_including_cyrillic(db):
    assert await db.add_habit(1, "Пить воду") is not None
    assert await db.add_habit(1, "ПИТЬ ВОДУ") is None
    assert await db.add_habit(1, "пить воду") is None
    assert await db.add_habit(2, "пить воду") is not None  # other user
    assert await db.add_habit(1, "Straße") is not None
    assert await db.add_habit(1, "STRASSE") is None  # casefold, not just lower()
    assert [h.name for h in await db.list_habits(1)] == ["Пить воду", "Straße"]  # names unchanged


async def test_fresh_database_gets_current_schema_version(tmp_path):
    path = tmp_path / "fresh.db"
    database = Database(path)
    await database.connect()
    await database.close()
    assert user_version(path) == SCHEMA_VERSION


async def test_newer_schema_version_is_refused(tmp_path):
    path = tmp_path / "future.db"
    con = sqlite3.connect(path)
    con.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    con.close()
    with pytest.raises(RuntimeError, match="newer"):
        await Database(path).connect()


async def test_migration_of_legacy_database_keeps_all_data(tmp_path):
    path = tmp_path / "old.db"
    make_legacy_db(path)
    assert user_version(path) == 0

    database = Database(path)
    await database.connect()
    try:
        assert user_version(path) == SCHEMA_VERSION
        habits = await database.list_habits(1)
        # Nothing is dropped or merged: duplicates are kept and renamed, oldest keeps its name.
        assert [(h.id, h.name) for h in habits] == [
            (1, "Read"),
            (2, "read (2)"),
            (3, "Пить воду"),
            (4, "ПИТЬ ВОДУ (2)"),
            (6, "READ (3)"),
        ]
        assert [(h.id, h.name) for h in await database.list_habits(2)] == [(5, "Read")]
        # Check-ins survived (dropping the old table must not cascade-delete them).
        assert await database.get_checkin_days(1) == {date(2026, 10, 1), date(2026, 10, 2)}
        assert await database.get_checkin_days(2) == {date(2026, 10, 1)}
        assert await database.get_checkin_days(4) == {date(2026, 10, 3)}
        assert await database.get_checkin_days(5) == {date(2026, 10, 1)}
        reminder = await database.get_reminder(1)
        assert reminder is not None and (reminder.chat_id, reminder.time) == (100, "21:30")
        async with database.conn.execute("SELECT created_at FROM habits WHERE id = 2") as cur:
            assert (await cur.fetchone())[0] == "2026-01-02 10:00:00"
        async with database.conn.execute("PRAGMA foreign_key_check") as cur:
            assert await cur.fetchall() == []
        async with database.conn.execute("PRAGMA foreign_keys") as cur:
            assert (await cur.fetchone())[0] == 1

        # The new constraints are active, ids are not reused and cascades still work.
        assert await database.add_habit(1, "ЧИТАТЬ") is not None
        assert await database.add_habit(1, "читать") is None
        assert await database.add_habit(1, "READ") is None
        created = await database.add_habit(1, "New")
        assert created is not None and created.id > 7
        assert await database.delete_habit(1, 1) is True
        assert await database.get_checkin_days(1) == set()
    finally:
        await database.close()


async def test_migration_is_idempotent_and_reopen_keeps_data(tmp_path):
    path = tmp_path / "old.db"
    make_legacy_db(path)
    for _ in range(2):
        database = Database(path)
        await database.connect()
        assert len(await database.list_habits(1)) == 5
        await database.close()
    assert user_version(path) == SCHEMA_VERSION


async def test_migration_of_empty_legacy_database(tmp_path):
    path = tmp_path / "empty.db"
    con = sqlite3.connect(path)
    con.executescript(LEGACY_SCHEMA)
    con.close()
    database = Database(path)
    await database.connect()
    assert await database.list_habits(1) == []
    assert (await database.add_habit(1, "Read")) is not None
    assert await database.add_habit(1, "read") is None
    await database.close()


async def test_failed_migration_rolls_back(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    make_legacy_db(path)

    def boom(_name):
        raise ValueError("boom")

    monkeypatch.setattr("habit_bot.db.name_key", boom)
    with pytest.raises(ValueError, match="boom"):
        await Database(path).connect()
    monkeypatch.undo()
    assert user_version(path) == 0
    con = sqlite3.connect(path)
    assert con.execute("SELECT COUNT(*) FROM habits").fetchone()[0] == 6
    assert con.execute("SELECT COUNT(*) FROM checkins").fetchone()[0] == 5
    con.close()
    database = Database(path)  # and it can still be migrated afterwards
    await database.connect()
    assert len(await database.list_habits(1)) == 5
    await database.close()


# --- batched queries ---------------------------------------------------------------------------


async def test_list_habits_with_done_flags(db):
    a = await db.add_habit(1, "A")
    b = await db.add_habit(1, "B")
    await db.add_habit(2, "Other")
    await db.add_checkin(a.id, date(2026, 10, 3))
    await db.add_checkin(b.id, date(2026, 10, 2))
    result = await db.list_habits_with_done(1, date(2026, 10, 3))
    assert [(h.name, done) for h, done in result] == [("A", True), ("B", False)]


async def test_get_checkin_days_many(db):
    a = await db.add_habit(1, "A")
    b = await db.add_habit(1, "B")
    c = await db.add_habit(1, "C")
    await db.add_checkin(a.id, date(2026, 10, 1))
    await db.add_checkin(a.id, date(2026, 10, 2))
    await db.add_checkin(c.id, date(2026, 10, 3))
    assert await db.get_checkin_days_many([a.id, b.id, c.id]) == {
        a.id: {date(2026, 10, 1), date(2026, 10, 2)},
        b.id: set(),
        c.id: {date(2026, 10, 3)},
    }
    assert await db.get_checkin_days_many([]) == {}
