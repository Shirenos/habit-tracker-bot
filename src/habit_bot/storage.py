"""Storage interface: everything the rest of the bot needs from a database.

Two implementations exist: ``habit_bot.db.Database`` (SQLite + WAL, the default) and
``habit_bot.pg.PostgresStorage`` (PostgreSQL via asyncpg). Services depend on this ``Storage``
protocol rather than on a concrete database; ``habit_bot.factory.create_storage`` picks one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Protocol


def name_key(name: str) -> str:
    """Key used for case-insensitive uniqueness (``casefold`` also handles Cyrillic)."""
    return name.casefold()


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


@dataclass(frozen=True, slots=True)
class AdminStats:
    """Aggregate numbers shown on the admin panel."""

    total_users: int  # distinct users with at least one habit or a reminder
    active_users_7d: int  # users with a check-in on any of the last 7 days (today included)
    total_habits: int
    checkins_today: int
    db_size_bytes: int  # on-disk size of the database (including the WAL file); 0 if in memory


class Storage(Protocol):
    """Async repository used by the services."""

    async def connect(self) -> None: ...

    async def close(self) -> None: ...

    # habits
    async def add_habit(self, user_id: int, name: str) -> Habit | None: ...

    async def list_habits(self, user_id: int) -> list[Habit]: ...

    async def list_habits_with_done(self, user_id: int, day: date) -> list[tuple[Habit, bool]]: ...

    async def get_habit(self, user_id: int, habit_id: int) -> Habit | None: ...

    async def delete_habit(self, user_id: int, habit_id: int) -> bool: ...

    # check-ins
    async def add_checkin(self, habit_id: int, day: date) -> bool: ...

    async def get_checkin_days(self, habit_id: int) -> set[date]: ...

    async def get_checkin_days_many(self, habit_ids: Sequence[int]) -> dict[int, set[date]]: ...

    # reminders
    async def set_reminder(self, user_id: int, chat_id: int, time: str) -> None: ...

    async def remove_reminder(self, user_id: int) -> bool: ...

    async def get_reminder(self, user_id: int) -> Reminder | None: ...

    async def list_reminders(self) -> list[Reminder]: ...

    # admin
    async def get_admin_stats(self, today: date) -> AdminStats: ...
