"""Daily reminders driven by a small asyncio scheduler (no extra dependencies)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter

from habit_bot.storage import Storage

logger = logging.getLogger(__name__)

_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")

SendFunc = Callable[..., Awaitable[Any]]
# Builds the reminder for a user: ``(text, reply_markup)`` or ``None`` to skip today's reminder.
ComposeFunc = Callable[[int], Awaitable[tuple[str, Any] | None]]
NowFunc = Callable[[ZoneInfo], datetime]
SleepFunc = Callable[[float], Awaitable[Any]]

# After a reminder was sent (or skipped as a duplicate) the scheduler never sleeps less than this,
# so a timer that fires a hair early cannot turn into a second send for the same local date.
MIN_SLEEP_SECONDS = 5.0


def parse_hhmm(value: str) -> time | None:
    """Parse ``HH:MM`` (24h). Returns ``None`` when invalid."""
    m = _TIME_RE.match(value.strip())
    return time(int(m.group(1)), int(m.group(2))) if m else None


def _as_utc(moment: datetime) -> datetime:
    """Aware datetimes are converted to UTC; naive ones are returned unchanged."""
    return moment.astimezone(UTC) if moment.tzinfo is not None else moment


def next_occurrence(target: time, now: datetime) -> datetime:
    """The next moment strictly after ``now`` whose wall-clock time is ``target``.

    The comparison is done in UTC: for datetimes sharing one ``tzinfo`` Python compares the naive
    wall-clock fields and ignores UTC offsets, which is wrong around DST changes.
    """
    candidate = now.replace(hour=target.hour, minute=target.minute, second=0, microsecond=0)
    if _as_utc(candidate) <= _as_utc(now):
        candidate += timedelta(days=1)  # wall-clock arithmetic: the same time tomorrow
    return candidate


def seconds_until(target: time, now: datetime) -> float:
    """Real seconds from ``now`` until the next occurrence of ``target`` (always > 0).

    Both moments are converted to UTC before subtracting, so a day with a DST change is
    23 or 25 hours long instead of a naive 24.
    """
    return (_as_utc(next_occurrence(target, now)) - _as_utc(now)).total_seconds()


class ReminderScheduler:
    """Keeps one asyncio task per user that fires once a day at the chosen time."""

    MESSAGE = "⏰ Время заглянуть в привычки! Откройте /today и отметьте сделанное."

    def __init__(
        self,
        db: Storage,
        send: SendFunc,
        tz: ZoneInfo,
        compose: ComposeFunc | None = None,
        *,
        now: NowFunc = datetime.now,
        sleep: SleepFunc = asyncio.sleep,
    ) -> None:
        self._db = db
        self._send = send
        self._tz = tz
        self._compose = compose
        self._now = now  # injectable clock and sleep keep the scheduler testable
        self._sleep = sleep
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
        task = self._tasks.pop(user_id, None)
        # A task may remove its own reminder (see ``_deliver``); it then simply returns.
        if task is not None and task is not asyncio.current_task():
            task.cancel()

    def _schedule(self, user_id: int, chat_id: int, at: time) -> None:
        self._cancel(user_id)
        self._tasks[user_id] = asyncio.create_task(self._run(user_id, chat_id, at))

    async def _run(self, user_id: int, chat_id: int, at: time) -> None:
        last_sent: date | None = None  # local date of the target we already delivered
        while True:
            target = next_occurrence(at, self._now(self._tz))
            if target.date() == last_sent:
                # Woke up slightly before the target and already sent: wait it out.
                await self._sleep(MIN_SLEEP_SECONDS)
                continue
            delay = (_as_utc(target) - _as_utc(self._now(self._tz))).total_seconds()
            await self._sleep(max(delay, 0.0))
            last_sent = target.date()
            if not await self._deliver(user_id, chat_id):
                return
            await self._sleep(MIN_SLEEP_SECONDS)

    async def _deliver(self, user_id: int, chat_id: int) -> bool:
        """Send today's reminder. Returns ``False`` when the reminder was removed for good."""
        try:
            if self._compose is None:
                message: tuple[str, Any] | None = (self.MESSAGE, None)
            else:
                message = await self._compose(user_id)
        except Exception:
            logger.exception("Failed to compose reminder for user %s", user_id)
            return True
        if message is None:
            return True
        text, markup = message

        for attempt in (1, 2):
            try:
                if self._compose is None:
                    await self._send(chat_id, text)
                else:
                    await self._send(chat_id, text, reply_markup=markup)
                return True
            except TelegramForbiddenError:
                logger.info(
                    "Chat %s is unavailable (blocked or gone); removing the reminder of user %s",
                    chat_id,
                    user_id,
                )
                await self.clear(user_id)
                return False
            except TelegramRetryAfter as exc:
                if attempt == 2:
                    logger.warning("Flood control again for chat %s; skipping reminder", chat_id)
                    return True
                logger.warning(
                    "Flood control for chat %s: retrying in %s s", chat_id, exc.retry_after
                )
                await self._sleep(exc.retry_after)
            except Exception:
                logger.exception("Failed to send reminder to chat %s", chat_id)
                return True
        return True
