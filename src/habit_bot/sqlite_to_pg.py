"""One-off, idempotent copy of an existing SQLite database into PostgreSQL.

Used by ``scripts/migrate_sqlite_to_postgres.py``. Habit ids are preserved (check-ins reference
them) and the id sequence is moved past the largest copied id. Rows that already exist in
PostgreSQL are left untouched, so running the copy twice does not duplicate anything.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from habit_bot.db import SCHEMA_VERSION as SQLITE_SCHEMA_VERSION
from habit_bot.pg import PostgresStorage


@dataclass(frozen=True, slots=True)
class CopyReport:
    """Rows newly inserted into PostgreSQL (rows that were already there are not counted)."""

    habits: int
    checkins: int
    reminders: int


def _parse_created_at(value: str) -> datetime:
    """SQLite stores ``datetime('now')`` as naive UTC text."""
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def read_sqlite(
    path: Path,
) -> tuple[
    list[tuple[int, int, str, str, datetime]], list[tuple[int, date]], list[tuple[int, int, str]]
]:
    """Read habits, check-ins and reminders from a SQLite file (opened read-only)."""
    if not path.is_file():
        raise FileNotFoundError(f"SQLite database not found: {path}")
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        version = con.execute("PRAGMA user_version").fetchone()[0]
        if version != SQLITE_SCHEMA_VERSION:
            raise RuntimeError(
                f"SQLite schema version is {version}, expected {SQLITE_SCHEMA_VERSION}. "
                "Start the bot once on this database so it is migrated, then run this again."
            )
        habits = [
            (r[0], r[1], r[2], r[3], _parse_created_at(r[4]))
            for r in con.execute(
                "SELECT id, user_id, name, name_key, created_at FROM habits ORDER BY id"
            )
        ]
        checkins = [
            (r[0], date.fromisoformat(r[1]))
            for r in con.execute("SELECT habit_id, day FROM checkins ORDER BY habit_id, day")
        ]
        reminders = [
            (r[0], r[1], r[2]) for r in con.execute("SELECT user_id, chat_id, time FROM reminders")
        ]
    finally:
        con.close()
    return habits, checkins, reminders


async def copy_sqlite_to_postgres(sqlite_path: Path, storage: PostgresStorage) -> CopyReport:
    """Copy everything in one transaction; ``storage`` must already be connected (migrated)."""
    habits, checkins, reminders = read_sqlite(sqlite_path)
    async with storage.pool.acquire() as conn, conn.transaction():
        before = {
            t: await conn.fetchval(f"SELECT COUNT(*) FROM {t}")
            for t in ("habits", "checkins", "reminders")
        }
        await conn.executemany(
            "INSERT INTO habits (id, user_id, name, name_key, created_at) "
            "VALUES ($1, $2, $3, $4, $5) ON CONFLICT DO NOTHING",
            habits,
        )
        await conn.executemany(
            "INSERT INTO checkins (habit_id, day) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            checkins,
        )
        await conn.executemany(
            "INSERT INTO reminders (user_id, chat_id, time) VALUES ($1, $2, $3) "
            "ON CONFLICT (user_id) DO NOTHING",
            reminders,
        )
        # Next generated id must not collide with the ids we just copied.
        await conn.execute(
            "SELECT setval(pg_get_serial_sequence('habits', 'id'), "
            "GREATEST((SELECT COALESCE(MAX(id), 0) FROM habits), 1), "
            "(SELECT COUNT(*) FROM habits) > 0)"
        )
        after = {
            t: await conn.fetchval(f"SELECT COUNT(*) FROM {t}")
            for t in ("habits", "checkins", "reminders")
        }
    return CopyReport(
        habits=after["habits"] - before["habits"],
        checkins=after["checkins"] - before["checkins"],
        reminders=after["reminders"] - before["reminders"],
    )
