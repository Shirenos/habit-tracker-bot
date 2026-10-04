import asyncio
import logging
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import SendMessage

from habit_bot.config import ConfigError, load_settings
from habit_bot.services.reminders import (
    MIN_SLEEP_SECONDS,
    ReminderScheduler,
    next_occurrence,
    parse_hhmm,
    seconds_until,
)

NY = ZoneInfo("America/New_York")
UTC_TZ = ZoneInfo("UTC")


class FakeClock:
    """Virtual time: ``sleep`` jumps forward instantly; blocks once ``limit`` is reached."""

    def __init__(self, start: datetime, days: int, early: float = 0.0) -> None:
        self.utc = start.astimezone(UTC)
        self.limit = self.utc + timedelta(days=days)
        self.early = early  # long sleeps wake this many seconds before the deadline
        self.sleeps: list[float] = []
        self.blocked = asyncio.Event()

    def now(self, tz: ZoneInfo) -> datetime:
        return self.utc.astimezone(tz)

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        advance = seconds - self.early if seconds > 60 else seconds
        if self.utc + timedelta(seconds=advance) > self.limit:
            self.blocked.set()
            await asyncio.Event().wait()  # until the scheduler task is cancelled
        self.utc += timedelta(seconds=advance)
        await asyncio.sleep(0)

    async def run_until_limit(self) -> None:
        await asyncio.wait_for(self.blocked.wait(), timeout=5)


def minute(moment: datetime) -> datetime:
    """Round to the nearest minute (the fake clock may wake a few ms early)."""
    return (moment + timedelta(seconds=30)).replace(second=0, microsecond=0)


def make_scheduler(db, clock, send, tz=UTC_TZ, compose=None):
    return ReminderScheduler(db, send, tz, compose, now=clock.now, sleep=clock.sleep)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("09:30", time(9, 30)), ("9:05", time(9, 5)), ("00:00", time(0, 0)), ("23:59", time(23, 59))],
)
def test_parse_hhmm_valid(raw, expected):
    assert parse_hhmm(raw) == expected


@pytest.mark.parametrize("raw", ["", "24:00", "12:60", "abc", "1230", "12:5", "-1:00"])
def test_parse_hhmm_invalid(raw):
    assert parse_hhmm(raw) is None


def test_seconds_until_same_day_and_next_day():
    now = datetime(2026, 10, 3, 10, 0, 0)
    assert seconds_until(time(11, 0), now) == 3600
    assert seconds_until(time(9, 0), now) == 23 * 3600
    assert seconds_until(time(10, 0), now) == 24 * 3600  # already passed this minute


async def test_scheduler_persists_and_fires(db):
    sent: list[tuple[int, str]] = []

    async def send(chat_id: int, text: str) -> None:
        sent.append((chat_id, text))

    clock = FakeClock(datetime(2026, 10, 3, 7, 0, tzinfo=UTC), days=1)
    scheduler = make_scheduler(db, clock, send)
    await scheduler.set(1, 100, time(8, 0))
    await clock.run_until_limit()
    await scheduler.stop()

    assert sent == [(100, ReminderScheduler.MESSAGE)]
    assert [r.time for r in await db.list_reminders()] == ["08:00"]


async def test_scheduler_restores_from_db_and_clears(db):
    async def send(chat_id: int, text: str) -> None: ...

    await db.set_reminder(1, 100, "08:00")
    scheduler = ReminderScheduler(db, send, ZoneInfo("UTC"))
    await scheduler.start()
    assert 1 in scheduler._tasks
    assert await scheduler.clear(1) is True
    assert 1 not in scheduler._tasks
    await scheduler.stop()


def test_config_requires_token(monkeypatch, tmp_path):
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    with pytest.raises(ConfigError):
        load_settings(tmp_path / "missing.env")


def test_config_reads_env_file(monkeypatch, tmp_path):
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    monkeypatch.delenv("TIMEZONE", raising=False)
    env = tmp_path / ".env"
    env.write_text("BOT_TOKEN=dummy-test-token\nTIMEZONE=Europe/Moscow\n")
    settings = load_settings(env)
    assert settings.bot_token == "dummy-test-token"
    assert str(settings.timezone) == "Europe/Moscow"
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    monkeypatch.delenv("TIMEZONE", raising=False)


def test_config_rejects_bad_timezone(monkeypatch, tmp_path):
    monkeypatch.setenv("BOT_TOKEN", "x")
    monkeypatch.setenv("TIMEZONE", "Mars/Olympus")
    with pytest.raises(ConfigError):
        load_settings(tmp_path / "missing.env")


async def test_scheduler_uses_composed_message_and_can_skip(db):
    sent: list[tuple[int, str, object]] = []

    async def send(chat_id: int, text: str, reply_markup=None) -> None:
        sent.append((chat_id, text, reply_markup))

    async def compose(user_id: int):
        return None if user_id == 2 else (f"hello {user_id}", "KB")

    clock = FakeClock(datetime(2026, 10, 3, 7, 0, tzinfo=UTC), days=1)
    scheduler = make_scheduler(db, clock, send, compose=compose)
    await scheduler.set(1, 100, time(8, 0))
    await scheduler.set(2, 200, time(8, 0))  # composer returns None: nothing to remind about
    await clock.run_until_limit()
    await scheduler.stop()

    assert sent == [(100, "hello 1", "KB")]


async def test_scheduler_get(db):
    async def send(*_a, **_k) -> None: ...

    scheduler = ReminderScheduler(db, send, ZoneInfo("UTC"))
    assert await scheduler.get(1) is None
    await scheduler.set(1, 100, time(21, 30))
    assert await scheduler.get(1) == time(21, 30)
    await scheduler.stop()


async def test_reminder_composer_lists_only_open_habits(service):
    from habit_bot.views import reminder_composer

    compose = reminder_composer(service)
    assert await compose(1) is None  # no habits
    await service.add(1, "Read")
    await service.add(1, "Run")
    await service.done(1, 1)
    text, markup = await compose(1)
    assert "Время для привычек" in text
    datas = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert "done:2:t" in datas and "done:1:t" not in datas
    await service.done(1, 2)
    assert await compose(1) is None  # everything done: stay quiet


# --- DST-aware maths ---------------------------------------------------------------------------


def test_seconds_until_spring_forward_day_is_23_hours():
    now = datetime(2026, 3, 7, 12, 0, tzinfo=NY)  # EST; clocks jump at 02:00 on March 8
    assert seconds_until(time(12, 0), now) == 23 * 3600
    assert seconds_until(time(11, 0), now) == 22 * 3600  # 11:00 EDT tomorrow


def test_seconds_until_fall_back_day_is_25_hours():
    now = datetime(2026, 10, 31, 12, 0, tzinfo=NY)  # EDT; clocks go back at 02:00 on November 1
    assert seconds_until(time(12, 0), now) == 25 * 3600


def test_seconds_until_across_the_gap_uses_real_elapsed_time():
    now = datetime(2026, 3, 8, 1, 30, tzinfo=NY)  # 30 minutes before the jump
    # 03:30 EDT is exactly one real hour away (02:30 does not exist that day).
    assert seconds_until(time(3, 30), now) == 3600


def test_seconds_until_nonexistent_target_still_fires_once_that_day():
    now = datetime(2026, 3, 8, 0, 0, tzinfo=NY)
    due = next_occurrence(time(2, 30), now)  # 02:30 does not exist on March 8
    assert due.date() == now.date()
    assert 2 * 3600 <= seconds_until(time(2, 30), now) <= 3 * 3600


def test_seconds_until_other_zone_and_utc_inputs():
    now = datetime(2026, 10, 3, 10, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    assert seconds_until(time(11, 0), now) == 3600
    assert seconds_until(time(11, 0), now.astimezone(UTC)) == 4 * 3600  # 11:00 UTC is 14:00 MSK


# --- scheduler behaviour -----------------------------------------------------------------------


async def run_days(db, start, days, *, early=0.0, tz=UTC_TZ, at=time(8, 0), send=None):
    """Run a reminder for ``days`` virtual days; returns UTC instants of every delivery."""
    clock = FakeClock(start, days, early)
    fired: list[datetime] = []

    async def default_send(chat_id: int, text: str) -> None:
        fired.append(minute(clock.utc))

    scheduler = make_scheduler(db, clock, send or default_send, tz)
    await scheduler.set(1, 100, at)
    await clock.run_until_limit()
    await scheduler.stop()
    return fired, clock


async def test_scheduler_fires_once_per_day(db):
    fired, _ = await run_days(db, datetime(2026, 10, 3, 7, 0, tzinfo=UTC), days=3)
    assert fired == [datetime(2026, 10, d, 8, 0, tzinfo=UTC) for d in (3, 4, 5)]


@pytest.mark.parametrize(("at", "start_hour"), [(time(8, 0), 7), (time(0, 0), 23)])
async def test_scheduler_does_not_double_send_when_woken_early(db, at, start_hour):
    """A timer that fires a few ms early must not produce a second send for the same date."""
    start = datetime(2026, 10, 3, start_hour, 0, tzinfo=UTC)
    fired, clock = await run_days(db, start, days=3, early=0.002, at=at)
    assert len(fired) == 3
    assert len({f.date() for f in fired}) == 3  # one per local date
    assert all(b - a > timedelta(hours=23) for a, b in zip(fired, fired[1:], strict=False))
    assert MIN_SLEEP_SECONDS >= 1 and min(clock.sleeps) >= MIN_SLEEP_SECONDS - 1e-9


async def test_scheduler_never_busy_loops_right_after_a_send(db):
    _, clock = await run_days(db, datetime(2026, 10, 3, 7, 0, tzinfo=UTC), days=2, early=0.002)
    assert all(s >= MIN_SLEEP_SECONDS for s in clock.sleeps)


async def test_scheduler_handles_spring_forward_in_new_york(db):
    start = datetime(2026, 3, 7, 11, 0, tzinfo=NY)  # 16:00 UTC
    fired, _ = await run_days(db, start, days=2, tz=NY, at=time(12, 0))
    assert [f.astimezone(NY).strftime("%m-%d %H:%M") for f in fired] == [
        "03-07 12:00",
        "03-08 12:00",
        "03-09 12:00",
    ]
    # March 8 is only 23 hours after March 7 in real time, then 24 again.
    assert [b - a for a, b in zip(fired, fired[1:], strict=False)] == [
        timedelta(hours=23),
        timedelta(hours=24),
    ]


async def test_scheduler_handles_fall_back_in_new_york(db):
    start = datetime(2026, 10, 31, 11, 0, tzinfo=NY)
    fired, _ = await run_days(db, start, days=3, tz=NY, at=time(12, 0), early=0.002)
    assert [f.astimezone(NY).strftime("%m-%d %H:%M") for f in fired] == [
        "10-31 12:00",
        "11-01 12:00",
        "11-02 12:00",
    ]
    assert fired[1] - fired[0] == timedelta(hours=25)


async def test_scheduler_sends_once_in_the_dst_gap_and_the_repeated_hour(db):
    gap, _ = await run_days(
        db, datetime(2026, 3, 8, 0, 0, tzinfo=NY), days=2, tz=NY, at=time(2, 30), early=0.002
    )
    assert len(gap) == 2 and gap[0].astimezone(NY).date() != gap[1].astimezone(NY).date()
    repeated, _ = await run_days(
        db, datetime(2026, 11, 1, 0, 0, tzinfo=NY), days=2, tz=NY, at=time(1, 30), early=0.002
    )
    assert len(repeated) == 2  # 01:30 happens twice on November 1 but is sent once


# --- Telegram errors ---------------------------------------------------------------------------


def _method() -> SendMessage:
    return SendMessage(chat_id=100, text="x")


async def test_forbidden_removes_reminder_and_logs_once(db, caplog):
    calls: list[int] = []

    async def send(chat_id: int, text: str) -> None:
        calls.append(chat_id)
        raise TelegramForbiddenError(_method(), "Forbidden: bot was blocked by the user")

    caplog.set_level(logging.INFO, logger="habit_bot.services.reminders")
    clock = FakeClock(datetime(2026, 10, 3, 7, 0, tzinfo=UTC), days=5)
    scheduler = make_scheduler(db, clock, send)
    await scheduler.set(1, 100, time(8, 0))
    await asyncio.sleep(0.2)  # lets the task send, clear the reminder and finish
    await scheduler.stop()

    assert calls == [100]  # never retried on later days
    assert await db.list_reminders() == []
    assert await scheduler.get(1) is None
    assert 1 not in scheduler._tasks
    infos = [r for r in caplog.records if r.levelno == logging.INFO and "100" in r.getMessage()]
    assert len(infos) == 1
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


async def test_forbidden_with_composed_message_also_clears(db):
    async def send(chat_id: int, text: str, reply_markup=None) -> None:
        if chat_id == 100:
            raise TelegramForbiddenError(_method(), "Forbidden: chat not found")

    async def compose(user_id: int):
        return "hi", None

    clock = FakeClock(datetime(2026, 10, 3, 7, 0, tzinfo=UTC), days=2)
    scheduler = make_scheduler(db, clock, send, compose=compose)
    await scheduler.set(1, 100, time(8, 0))
    await scheduler.set(2, 200, time(23, 0))  # other users are unaffected
    await asyncio.sleep(0.2)
    await scheduler.stop()
    assert [r.user_id for r in await db.list_reminders()] == [2]


async def test_retry_after_waits_and_retries_once(db):
    attempts: list[str] = []

    async def send(chat_id: int, text: str) -> None:
        attempts.append(text)
        if len(attempts) == 1:
            raise TelegramRetryAfter(_method(), "Too Many Requests", retry_after=7)

    clock = FakeClock(datetime(2026, 10, 3, 7, 0, tzinfo=UTC), days=1)
    scheduler = make_scheduler(db, clock, send)
    await scheduler.set(1, 100, time(8, 0))
    await clock.run_until_limit()
    await scheduler.stop()

    assert len(attempts) == 2
    assert 7 in clock.sleeps
    assert await db.get_reminder(1) is not None  # reminder kept


async def test_retry_after_gives_up_after_one_retry_but_keeps_going(db, caplog):
    attempts: list[datetime] = []
    clock = FakeClock(datetime(2026, 10, 3, 7, 0, tzinfo=UTC), days=2)

    async def send(chat_id: int, text: str) -> None:
        attempts.append(minute(clock.utc))
        raise TelegramRetryAfter(_method(), "Too Many Requests", retry_after=3)

    scheduler = make_scheduler(db, clock, send)
    await scheduler.set(1, 100, time(8, 0))
    await clock.run_until_limit()
    await scheduler.stop()

    assert len(attempts) == 4  # two attempts per day, two days
    assert await db.get_reminder(1) is not None


async def test_other_errors_are_logged_and_next_day_still_fires(db, caplog):
    calls: list[int] = []

    async def send(chat_id: int, text: str) -> None:
        calls.append(chat_id)
        if len(calls) == 1:
            raise RuntimeError("boom")

    clock = FakeClock(datetime(2026, 10, 3, 7, 0, tzinfo=UTC), days=2)
    scheduler = make_scheduler(db, clock, send)
    await scheduler.set(1, 100, time(8, 0))
    await clock.run_until_limit()
    await scheduler.stop()

    assert calls == [100, 100]
    assert any("Failed to send reminder" in r.getMessage() for r in caplog.records)
    assert await db.get_reminder(1) is not None


async def test_compose_errors_are_logged_and_do_not_kill_the_task(db, caplog):
    sent: list[Any] = []

    async def send(chat_id: int, text: str, reply_markup=None) -> None:
        sent.append(text)

    async def compose(user_id: int):
        if not sent and not caplog.records:
            raise RuntimeError("db down")
        return "ok", None

    clock = FakeClock(datetime(2026, 10, 3, 7, 0, tzinfo=UTC), days=2)
    scheduler = make_scheduler(db, clock, send, compose=compose)
    await scheduler.set(1, 100, time(8, 0))
    await clock.run_until_limit()
    await scheduler.stop()
    assert sent == ["ok"]
