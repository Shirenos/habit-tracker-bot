"""Async SQLite storage layer built on aiosqlite."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path

import aiosqlite

from habit_bot.storage import AdminStats, Habit, Reminder, name_key

# Bump when the schema changes and add a step to ``Database._migrate``.
# 0 = legacy databases created before versioning, 1 = habits.name_key (case-insensitive names).
SCHEMA_VERSION = 1
BUSY_TIMEOUT_MS = 5000

SCHEMA = """
CREATE TABLE IF NOT EXISTS habits (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    name       TEXT    NOT NULL,
    name_key   TEXT    NOT NULL,
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (user_id, name_key)
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


__all__ = ["SCHEMA_VERSION", "AdminStats", "Database", "Habit", "Reminder", "name_key"]


class Database:
    """SQLite implementation of :class:`habit_bot.storage.Storage` (one connection, WAL mode).

    WAL lets readers and the writer work at the same time, ``synchronous=NORMAL`` is safe with WAL
    (a power loss may drop the last commits but never corrupts the file) and ``busy_timeout``
    makes a writer wait for a lock instead of failing at once.
    """

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
        try:
            await self._configure(self._conn)
            await self._init_schema(self._conn)
        except BaseException:
            await self.close()
            raise
        await self._conn.execute("PRAGMA foreign_keys = ON")

    async def _configure(self, conn: aiosqlite.Connection) -> None:
        """Apply connection pragmas (WAL is stored in the file, the others are per connection)."""
        await conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        if self._path != ":memory:":  # in-memory databases cannot use WAL
            async with conn.execute("PRAGMA journal_mode = WAL") as cur:
                row = await cur.fetchone()
            if row is None or str(row[0]).lower() != "wal":
                raise RuntimeError("Could not enable SQLite WAL mode")
            await conn.execute("PRAGMA synchronous = NORMAL")

    async def _init_schema(self, conn: aiosqlite.Connection) -> None:
        async with conn.execute("PRAGMA user_version") as cur:
            row = await cur.fetchone()
        version = int(row[0]) if row else 0
        if version > SCHEMA_VERSION:
            raise RuntimeError(
                f"Database schema version {version} is newer than supported ({SCHEMA_VERSION})."
            )
        if version == SCHEMA_VERSION:
            return
        async with conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'habits'"
        ) as cur:
            has_habits = await cur.fetchone() is not None
        if not has_habits:  # brand-new database: create the latest schema directly
            await conn.executescript(SCHEMA)
            await conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            await conn.commit()
            return
        await self._migrate(conn, version)

    @staticmethod
    async def _migrate(conn: aiosqlite.Connection, version: int) -> None:
        """Upgrade an existing database in place, one version at a time."""
        if version < 1:
            await _migrate_v0_to_v1(conn)

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    # -- habits ----------------------------------------------------------
    async def add_habit(self, user_id: int, name: str) -> Habit | None:
        """Create a habit; ``None`` if the user has one with that name (case-insensitive)."""
        try:
            cur = await self.conn.execute(
                "INSERT INTO habits (user_id, name, name_key) VALUES (?, ?, ?)",
                (user_id, name, name_key(name)),
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

    async def list_habits_with_done(self, user_id: int, day: date) -> list[tuple[Habit, bool]]:
        """Habits of ``user_id`` with a flag telling whether each was checked in on ``day``."""
        async with self.conn.execute(
            "SELECT h.id, h.user_id, h.name, "
            "EXISTS (SELECT 1 FROM checkins c WHERE c.habit_id = h.id AND c.day = ?) AS done "
            "FROM habits h WHERE h.user_id = ? ORDER BY h.id",
            (day.isoformat(), user_id),
        ) as cur:
            return [(Habit(r["id"], r["user_id"], r["name"]), bool(r["done"])) async for r in cur]

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

    # -- admin -----------------------------------------------------------
    async def get_admin_stats(self, today: date) -> AdminStats:
        """Aggregate numbers for the admin panel; ``today`` is the bot's local date."""
        week_start = today - timedelta(days=6)
        async with self.conn.execute(
            "SELECT COUNT(*) FROM (SELECT user_id FROM habits UNION SELECT user_id FROM reminders)"
        ) as cur:
            total_users = (await cur.fetchone() or (0,))[0]
        async with self.conn.execute(
            "SELECT COUNT(DISTINCT h.user_id) FROM checkins c "
            "JOIN habits h ON h.id = c.habit_id WHERE c.day BETWEEN ? AND ?",
            (week_start.isoformat(), today.isoformat()),
        ) as cur:
            active_users = (await cur.fetchone() or (0,))[0]
        async with self.conn.execute("SELECT COUNT(*) FROM habits") as cur:
            total_habits = (await cur.fetchone() or (0,))[0]
        async with self.conn.execute(
            "SELECT COUNT(*) FROM checkins WHERE day = ?", (today.isoformat(),)
        ) as cur:
            checkins_today = (await cur.fetchone() or (0,))[0]
        return AdminStats(
            total_users=total_users,
            active_users_7d=active_users,
            total_habits=total_habits,
            checkins_today=checkins_today,
            db_size_bytes=self.file_size(),
        )

    def file_size(self) -> int:
        """Bytes used on disk by the database file and its WAL (0 for in-memory databases)."""
        if self._path == ":memory:":
            return 0
        return sum(
            p.stat().st_size for p in (Path(self._path), Path(self._path + "-wal")) if p.exists()
        )

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

    async def get_checkin_days_many(self, habit_ids: Sequence[int]) -> dict[int, set[date]]:
        """Check-in days of several habits in one query (every id is present in the result)."""
        days: dict[int, set[date]] = {habit_id: set() for habit_id in habit_ids}
        if not days:
            return days
        placeholders = ", ".join("?" * len(days))
        async with self.conn.execute(
            f"SELECT habit_id, day FROM checkins WHERE habit_id IN ({placeholders})",
            list(days),
        ) as cur:
            async for r in cur:
                days[r["habit_id"]].add(date.fromisoformat(r["day"]))
        return days

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

    async def get_reminder(self, user_id: int) -> Reminder | None:
        async with self.conn.execute(
            "SELECT user_id, chat_id, time FROM reminders WHERE user_id = ?", (user_id,)
        ) as cur:
            r = await cur.fetchone()
        return Reminder(r["user_id"], r["chat_id"], r["time"]) if r else None

    async def list_reminders(self) -> list[Reminder]:
        async with self.conn.execute("SELECT user_id, chat_id, time FROM reminders") as cur:
            return [Reminder(r["user_id"], r["chat_id"], r["time"]) async for r in cur]


async def _migrate_v0_to_v1(conn: aiosqlite.Connection) -> None:
    """Add ``habits.name_key`` with ``UNIQUE (user_id, name_key)`` to a legacy database.

    ``name_key`` is backfilled with ``casefold(name)``. If a user has habits whose names collide
    once case is ignored (e.g. "Read" and "read"), the oldest keeps its name and the others get a
    numeric suffix ("read (2)"), so no habit or check-in is lost. The table is rebuilt in a
    single transaction with foreign keys off (otherwise dropping ``habits`` would cascade-delete
    every check-in); ids and ``created_at`` are preserved.
    """
    async with conn.execute("PRAGMA table_info(habits)") as cur:
        columns = {row["name"] async for row in cur}
    if "name_key" not in columns:
        await conn.commit()
        await conn.execute("PRAGMA foreign_keys = OFF")
        try:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                await _rebuild_habits_with_name_key(conn)
                await conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                async with conn.execute("PRAGMA foreign_key_check") as cur:
                    if await cur.fetchall():
                        raise RuntimeError("Foreign key check failed after migration")
            except BaseException:
                await conn.rollback()
                raise
            await conn.commit()
        finally:
            await conn.execute("PRAGMA foreign_keys = ON")
    else:  # column already there (e.g. migration interrupted by hand): just record the version
        await conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        await conn.commit()
    await conn.executescript(SCHEMA)  # creates any missing tables / indexes (all IF NOT EXISTS)


async def _rebuild_habits_with_name_key(conn: aiosqlite.Connection) -> None:
    async with conn.execute("SELECT seq FROM sqlite_sequence WHERE name = 'habits'") as cur:
        seq_row = await cur.fetchone()
    async with conn.execute("SELECT id, user_id, name, created_at FROM habits ORDER BY id") as cur:
        rows = await cur.fetchall()

    taken: set[tuple[int, str]] = set()
    prepared: list[tuple[int, int, str, str, str]] = []
    for r in rows:
        name: str = r["name"]
        candidate, n = name, 1
        while (r["user_id"], name_key(candidate)) in taken:
            n += 1
            candidate = f"{name} ({n})"
        taken.add((r["user_id"], name_key(candidate)))
        prepared.append((r["id"], r["user_id"], candidate, name_key(candidate), r["created_at"]))

    await conn.execute(
        """
        CREATE TABLE habits_new (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            name       TEXT    NOT NULL,
            name_key   TEXT    NOT NULL,
            created_at TEXT    NOT NULL DEFAULT (datetime('now')),
            UNIQUE (user_id, name_key)
        )
        """
    )
    await conn.executemany(
        "INSERT INTO habits_new (id, user_id, name, name_key, created_at) VALUES (?, ?, ?, ?, ?)",
        prepared,
    )
    await conn.execute("DROP TABLE habits")
    await conn.execute("ALTER TABLE habits_new RENAME TO habits")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_habits_user ON habits (user_id)")
    # Keep AUTOINCREMENT from reusing ids of habits deleted earlier.
    next_seq = max([seq_row["seq"] if seq_row else 0, *(p[0] for p in prepared)])
    await conn.execute("DELETE FROM sqlite_sequence WHERE name = 'habits'")
    if next_seq:
        await conn.execute(
            "INSERT INTO sqlite_sequence (name, seq) VALUES ('habits', ?)", (next_seq,)
        )
