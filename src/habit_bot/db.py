"""Async SQLite storage layer built on aiosqlite."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS habits (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    name       TEXT    NOT NULL,
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (user_id, name)
);
CREATE INDEX IF NOT EXISTS idx_habits_user ON habits (user_id);

CREATE TABLE IF NOT EXISTS checkins (
    habit_id INTEGER NOT NULL REFERENCES habits (id) ON DELETE CASCADE,
    day      TEXT    NOT NULL,
    PRIMARY KEY (habit_id, day)
);

CREATE TABLE IF NOT EXISTS reminders (
    user_id INTEGER PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    time    TEXT    NOT NULL
);
"""


@dataclass(frozen=True, slots=True)
class Habit:
    id: int
    user_id: int
    name: str


@dataclass(frozen=True, slots=True)
class Reminder:
    user_id: int
    chat_id: int
    time: str  # "HH:MM"


class Database:
    """Thin repository over a single SQLite connection."""

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        self._conn: aiosqlite.Connection | None = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not connected. Call connect() first.")
        return self._conn

    async def connect(self) -> None:
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys = ON")
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    # -- habits ----------------------------------------------------------
    async def add_habit(self, user_id: int, name: str) -> Habit | None:
        """Create a habit. Returns ``None`` if the user already has one with that name."""
        try:
            cur = await self.conn.execute(
                "INSERT INTO habits (user_id, name) VALUES (?, ?)", (user_id, name)
            )
        except aiosqlite.IntegrityError:
            return None
        await self.conn.commit()
        return Habit(id=cur.lastrowid or 0, user_id=user_id, name=name)

    async def list_habits(self, user_id: int) -> list[Habit]:
        async with self.conn.execute(
            "SELECT id, user_id, name FROM habits WHERE user_id = ? ORDER BY id", (user_id,)
        ) as cur:
            return [Habit(r["id"], r["user_id"], r["name"]) async for r in cur]

    async def get_habit(self, user_id: int, habit_id: int) -> Habit | None:
        async with self.conn.execute(
            "SELECT id, user_id, name FROM habits WHERE id = ? AND user_id = ?",
            (habit_id, user_id),
        ) as cur:
            r = await cur.fetchone()
        return Habit(r["id"], r["user_id"], r["name"]) if r else None

    async def delete_habit(self, user_id: int, habit_id: int) -> bool:
        cur = await self.conn.execute(
            "DELETE FROM habits WHERE id = ? AND user_id = ?", (habit_id, user_id)
        )
        await self.conn.commit()
        return cur.rowcount > 0

    # -- check-ins -------------------------------------------------------
    async def add_checkin(self, habit_id: int, day: date) -> bool:
        """Mark a habit done for ``day``. Returns False if it was already marked."""
        cur = await self.conn.execute(
            "INSERT OR IGNORE INTO checkins (habit_id, day) VALUES (?, ?)",
            (habit_id, day.isoformat()),
        )
        await self.conn.commit()
        return cur.rowcount > 0

    async def get_checkin_days(self, habit_id: int) -> set[date]:
        async with self.conn.execute(
            "SELECT day FROM checkins WHERE habit_id = ?", (habit_id,)
        ) as cur:
            return {date.fromisoformat(r["day"]) async for r in cur}

    # -- reminders -------------------------------------------------------
    async def set_reminder(self, user_id: int, chat_id: int, time: str) -> None:
        await self.conn.execute(
            "INSERT INTO reminders (user_id, chat_id, time) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET chat_id = excluded.chat_id, time = excluded.time",
            (user_id, chat_id, time),
        )
        await self.conn.commit()

    async def remove_reminder(self, user_id: int) -> bool:
        cur = await self.conn.execute("DELETE FROM reminders WHERE user_id = ?", (user_id,))
        await self.conn.commit()
        return cur.rowcount > 0

    async def list_reminders(self) -> list[Reminder]:
        async with self.conn.execute("SELECT user_id, chat_id, time FROM reminders") as cur:
            return [Reminder(r["user_id"], r["chat_id"], r["time"]) async for r in cur]
