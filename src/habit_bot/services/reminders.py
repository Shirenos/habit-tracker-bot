"""Daily reminders driven by a small asyncio scheduler (no extra dependencies)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from habit_bot.db import Database

logger = logging.getLogger(__name__)

_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")

SendFunc = Callable[..., Awaitable[Any]]
# Builds the reminder for a user: ``(text, reply_markup)`` or ``None`` to skip today's reminder.
ComposeFunc = Callable[[int], Awaitable[tuple[str, Any] | None]]


def parse_hhmm(value: str) -> time | None:
    """Parse ``HH:MM`` (24h). Returns ``None`` when invalid."""
    m = _TIME_RE.match(value.strip())
    return time(int(m.group(1)), int(m.group(2))) if m else None


def seconds_until(target: time, now: datetime) -> float:
    """Seconds from ``now`` until the next occurrence of ``target`` (always > 0)."""
    candidate = now.replace(hour=target.hour, minute=target.minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return (candidate - now).total_seconds()


class ReminderScheduler:
    """Keeps one asyncio task per user that fires once a day at the chosen time."""

    MESSAGE = "⏰ Время заглянуть в привычки! Откройте /today и отметьте сделанное."

    def __init__(
        self,
        db: Database,
        send: SendFunc,
        tz: ZoneInfo,
        compose: ComposeFunc | None = None,
    ) -> None:
        self._db = db
        self._send = send
        self._tz = tz
        self._compose = compose
        self._tasks: dict[int, asyncio.Task[None]] = {}

    async def start(self) -> None:
        """Re-create tasks for every reminder stored in the database."""
        for r in await self._db.list_reminders():
            if (t := parse_hhmm(r.time)) is not None:
                self._schedule(r.user_id, r.chat_id, t)

    async def set(self, user_id: int, chat_id: int, at: time) -> None:
        await self._db.set_reminder(user_id, chat_id, at.strftime("%H:%M"))
        self._schedule(user_id, chat_id, at)

    async def get(self, user_id: int) -> time | None:
        """The reminder time configured for ``user_id`` (``None`` when disabled)."""
        reminder = await self._db.get_reminder(user_id)
        return parse_hhmm(reminder.time) if reminder else None

    async def clear(self, user_id: int) -> bool:
        self._cancel(user_id)
        return await self._db.remove_reminder(user_id)

    async def stop(self) -> None:
        tasks = list(self._tasks.values())
        self._tasks.clear()
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task

    def _cancel(self, user_id: int) -> None:
        if task := self._tasks.pop(user_id, None):
            task.cancel()

    def _schedule(self, user_id: int, chat_id: int, at: time) -> None:
        self._cancel(user_id)
        self._tasks[user_id] = asyncio.create_task(self._run(user_id, chat_id, at))

    async def _run(self, user_id: int, chat_id: int, at: time) -> None:
        while True:
            await asyncio.sleep(seconds_until(at, datetime.now(self._tz)))
            try:
                if self._compose is None:
                    await self._send(chat_id, self.MESSAGE)
                elif (composed := await self._compose(user_id)) is not None:
                    text, markup = composed
                    await self._send(chat_id, text, reply_markup=markup)
            except Exception:
                logger.exception("Failed to send reminder to chat %s", chat_id)
