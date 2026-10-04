"""Business logic for habits, check-ins and statistics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from zoneinfo import ZoneInfo

from habit_bot.db import Database, Habit
from habit_bot.services import streaks

MAX_NAME_LENGTH = 64
MAX_HABITS_PER_USER = 30


class AddResult(Enum):
    OK = "ok"
    DUPLICATE = "duplicate"
    LIMIT = "limit"
    INVALID = "invalid"


class DoneResult(Enum):
    OK = "ok"
    ALREADY = "already"
    NOT_FOUND = "not_found"


@dataclass(frozen=True, slots=True)
class HabitStats:
    habit: Habit
    current: int
    longest: int
    total: int
    week: list[tuple[date, bool]]

    @property
    def done_today(self) -> bool:
        """``week`` always ends with today, so the last flag tells if it is done."""
        return bool(self.week) and self.week[-1][1]


class HabitService:
    def __init__(self, db: Database, tz: ZoneInfo) -> None:
        self._db = db
        self._tz = tz

    @property
    def timezone(self) -> ZoneInfo:
        return self._tz

    def today(self) -> date:
        return datetime.now(self._tz).date()

    async def add(self, user_id: int, name: str) -> tuple[AddResult, Habit | None]:
        name = " ".join(name.split())
        if not name or len(name) > MAX_NAME_LENGTH:
            return AddResult.INVALID, None
        if len(await self._db.list_habits(user_id)) >= MAX_HABITS_PER_USER:
            return AddResult.LIMIT, None
        habit = await self._db.add_habit(user_id, name)
        return (AddResult.OK, habit) if habit else (AddResult.DUPLICATE, None)

    async def list_with_status(self, user_id: int) -> list[tuple[Habit, bool]]:
        """Habits paired with whether each was completed today."""
        return await self._db.list_habits_with_done(user_id, self.today())

    async def done(
        self, user_id: int, habit_id: int, day: date | None = None
    ) -> tuple[DoneResult, Habit | None]:
        habit = await self._db.get_habit(user_id, habit_id)
        if habit is None:
            return DoneResult.NOT_FOUND, None
        created = await self._db.add_checkin(habit.id, day or self.today())
        return (DoneResult.OK if created else DoneResult.ALREADY), habit

    async def get(self, user_id: int, habit_id: int) -> Habit | None:
        return await self._db.get_habit(user_id, habit_id)

    async def delete(self, user_id: int, habit_id: int) -> bool:
        return await self._db.delete_habit(user_id, habit_id)

    async def stats(self, user_id: int, today: date | None = None) -> list[HabitStats]:
        today = today or self.today()
        habits = await self._db.list_habits(user_id)
        days_by_habit = await self._db.get_checkin_days_many([h.id for h in habits])
        result = []
        for habit in habits:
            days = days_by_habit[habit.id]
            result.append(
                HabitStats(
                    habit=habit,
                    current=streaks.current_streak(days, today),
                    longest=streaks.longest_streak(days),
                    total=len(days),
                    week=streaks.last_n_days(days, today, 7),
                )
            )
        return result
