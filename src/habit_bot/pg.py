"""PostgreSQL implementation of :class:`habit_bot.storage.Storage` (asyncpg connection pool).

``asyncpg`` is an optional dependency (``pip install .[postgres]``) and is imported lazily in
:meth:`PostgresStorage.connect`, so SQLite-only installs never need it.

The schema mirrors the SQLite one (see ``habit_bot.db``): same tables and columns, ``name_key``
holds ``casefold(name)`` for case-insensitive uniqueness, and migrations are tracked in a
one-row ``schema_version`` table. Timestamps are stored in UTC (``timestamptz``), reminder times
stay ``HH:MM`` strings in the bot's configured timezone, exactly as in SQLite.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from habit_bot.storage import AdminStats, Habit, Reminder, name_key

if TYPE_CHECKING:
    import asyncpg

logger = logging.getLogger(__name__)

# Bump when the schema changes and append a step to ``_MIGRATIONS``.
SCHEMA_VERSION = 1

# Arbitrary constant: serialises concurrent migrations from several bot processes.
_MIGRATION_LOCK_ID = 7_283_461_905

_SCHEMA_V1 = """
CREATE TABLE habits (
    id         BIGSERIAL   PRIMARY KEY,
    user_id    BIGINT      NOT NULL,
    name       TEXT        NOT NULL,
    name_key   TEXT        NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, name_key)
);
CREATE INDEX idx_habits_user ON habits (user_id);

CREATE TABLE checkins (
    habit_id BIGINT NOT NULL REFERENCES habits (id) ON DELETE CASCADE,
    day      DATE   NOT NULL,
    PRIMARY KEY (habit_id, day)
);

CREATE TABLE reminders (
    user_id BIGINT PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    time    TEXT   NOT NULL
);
"""

# Step ``i`` upgrades the schema from version ``i`` to ``i + 1``.
_MIGRATIONS: list[str] = [_SCHEMA_V1]


def is_postgres_url(url: str) -> bool:
    return urlsplit(url).scheme in {"postgresql", "postgres"}


class PostgresStorage:
    """asyncpg-based storage; one pool shared by all handlers."""

    def __init__(
        self,
        dsn: str,
        *,
        schema: str | None = None,
        min_size: int = 1,
        max_size: int = 10,
    ) -> None:
        self._dsn = dsn
        self._schema = schema  # optional schema (search_path); used by the tests for isolation
        self._min_size = min_size
        self._max_size = max_size
        self._pool: asyncpg.Pool[Any] | None = None

    @property
    def pool(self) -> asyncpg.Pool[Any]:
        if self._pool is None:
            raise RuntimeError("Database is not connected. Call connect() first.")
        return self._pool

    async def connect(self) -> None:
        try:
            import asyncpg
        except ImportError as exc:  # pragma: no cover - depends on the installed extras
            raise RuntimeError(
                "DATABASE_URL is set but asyncpg is not installed. "
                "Install it with: pip install 'habit-tracker-bot[postgres]'"
            ) from exc
        server_settings = {"search_path": self._schema} if self._schema else None
        self._pool = await asyncpg.create_pool(
            self._dsn,
            min_size=self._min_size,
            max_size=self._max_size,
            server_settings=server_settings,
        )
        try:
            await self._migrate()
        except BaseException:
            await self.close()
            raise

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    # -- schema ----------------------------------------------------------
    async def _migrate(self) -> None:
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", _MIGRATION_LOCK_ID)
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"
            )
            row = await conn.fetchrow("SELECT version FROM schema_version")
            if row is None:
                await conn.execute("INSERT INTO schema_version (version) VALUES (0)")
            version = int(row["version"]) if row else 0
            if version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"Database schema version {version} is newer than supported ({SCHEMA_VERSION})."
                )
            for step in range(version, SCHEMA_VERSION):
                await conn.execute(_MIGRATIONS[step])
                await conn.execute("UPDATE schema_version SET version = $1", step + 1)

    # -- habits ----------------------------------------------------------
    async def add_habit(self, user_id: int, name: str) -> Habit | None:
        """Create a habit; ``None`` if the user has one with that name (case-insensitive)."""
        habit_id = await self.pool.fetchval(
            "INSERT INTO habits (user_id, name, name_key) VALUES ($1, $2, $3) "
            "ON CONFLICT (user_id, name_key) DO NOTHING RETURNING id",
            user_id,
            name,
            name_key(name),
        )
        return None if habit_id is None else Habit(id=habit_id, user_id=user_id, name=name)

    async def list_habits(self, user_id: int) -> list[Habit]:
        rows = await self.pool.fetch(
            "SELECT id, user_id, name FROM habits WHERE user_id = $1 ORDER BY id", user_id
        )
        return [Habit(r["id"], r["user_id"], r["name"]) for r in rows]

    async def list_habits_with_done(self, user_id: int, day: date) -> list[tuple[Habit, bool]]:
        rows = await self.pool.fetch(
            "SELECT h.id, h.user_id, h.name, "
            "EXISTS (SELECT 1 FROM checkins c WHERE c.habit_id = h.id AND c.day = $1) AS done "
            "FROM habits h WHERE h.user_id = $2 ORDER BY h.id",
            day,
            user_id,
        )
        return [(Habit(r["id"], r["user_id"], r["name"]), bool(r["done"])) for r in rows]

    async def get_habit(self, user_id: int, habit_id: int) -> Habit | None:
        r = await self.pool.fetchrow(
            "SELECT id, user_id, name FROM habits WHERE id = $1 AND user_id = $2",
            habit_id,
            user_id,
        )
        return Habit(r["id"], r["user_id"], r["name"]) if r else None

    async def delete_habit(self, user_id: int, habit_id: int) -> bool:
        status = await self.pool.execute(
            "DELETE FROM habits WHERE id = $1 AND user_id = $2", habit_id, user_id
        )
        return _affected(status) > 0

    # -- check-ins -------------------------------------------------------
    async def add_checkin(self, habit_id: int, day: date) -> bool:
        """Mark a habit done for ``day``. Returns False if it was already marked."""
        status = await self.pool.execute(
            "INSERT INTO checkins (habit_id, day) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            habit_id,
            day,
        )
        return _affected(status) > 0

    async def get_checkin_days(self, habit_id: int) -> set[date]:
        rows = await self.pool.fetch("SELECT day FROM checkins WHERE habit_id = $1", habit_id)
        return {r["day"] for r in rows}

    async def get_checkin_days_many(self, habit_ids: Sequence[int]) -> dict[int, set[date]]:
        result: dict[int, set[date]] = {hid: set() for hid in habit_ids}
        if not habit_ids:
            return result
        rows = await self.pool.fetch(
            "SELECT habit_id, day FROM checkins WHERE habit_id = ANY($1::bigint[])",
            list(habit_ids),
        )
        for r in rows:
            result[r["habit_id"]].add(r["day"])
        return result

    # -- reminders -------------------------------------------------------
    async def set_reminder(self, user_id: int, chat_id: int, time: str) -> None:
        await self.pool.execute(
            "INSERT INTO reminders (user_id, chat_id, time) VALUES ($1, $2, $3) "
            "ON CONFLICT (user_id) DO UPDATE SET chat_id = excluded.chat_id, time = excluded.time",
            user_id,
            chat_id,
            time,
        )

    async def remove_reminder(self, user_id: int) -> bool:
        status = await self.pool.execute("DELETE FROM reminders WHERE user_id = $1", user_id)
        return _affected(status) > 0

    async def get_reminder(self, user_id: int) -> Reminder | None:
        r = await self.pool.fetchrow(
            "SELECT user_id, chat_id, time FROM reminders WHERE user_id = $1", user_id
        )
        return Reminder(r["user_id"], r["chat_id"], r["time"]) if r else None

    async def list_reminders(self) -> list[Reminder]:
        rows = await self.pool.fetch("SELECT user_id, chat_id, time FROM reminders")
        return [Reminder(r["user_id"], r["chat_id"], r["time"]) for r in rows]

    # -- admin -----------------------------------------------------------
    async def get_admin_stats(self, today: date) -> AdminStats:
        """Aggregate numbers for the admin panel; same definitions as the SQLite backend."""
        week_start = today - timedelta(days=6)
        async with self.pool.acquire() as conn:
            total_users = await conn.fetchval(
                "SELECT COUNT(*) FROM (SELECT user_id FROM habits UNION "
                "SELECT user_id FROM reminders) AS u"
            )
            active_users = await conn.fetchval(
                "SELECT COUNT(DISTINCT h.user_id) FROM checkins c "
                "JOIN habits h ON h.id = c.habit_id WHERE c.day BETWEEN $1 AND $2",
                week_start,
                today,
            )
            total_habits = await conn.fetchval("SELECT COUNT(*) FROM habits")
            checkins_today = await conn.fetchval(
                "SELECT COUNT(*) FROM checkins WHERE day = $1", today
            )
            db_size = await conn.fetchval("SELECT pg_database_size(current_database())")
        return AdminStats(
            total_users=int(total_users),
            active_users_7d=int(active_users),
            total_habits=int(total_habits),
            checkins_today=int(checkins_today),
            db_size_bytes=int(db_size),
        )


def _affected(status: str) -> int:
    """Rows affected, parsed from an asyncpg command tag such as ``INSERT 0 1`` / ``DELETE 3``."""
    try:
        return int(status.rsplit(" ", 1)[-1])
    except ValueError:  # pragma: no cover - unexpected tag
        return 0


__all__ = ["SCHEMA_VERSION", "PostgresStorage", "is_postgres_url"]
