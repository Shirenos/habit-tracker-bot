import asyncio
from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from habit_bot.config import ConfigError, load_settings
from habit_bot.services.reminders import ReminderScheduler, parse_hhmm, seconds_until


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


async def test_scheduler_persists_and_fires(db, monkeypatch):
    sent: list[tuple[int, str]] = []

    async def send(chat_id: int, text: str) -> None:
        sent.append((chat_id, text))

    # Make the scheduler fire immediately instead of waiting for wall-clock time.
    monkeypatch.setattr("habit_bot.services.reminders.seconds_until", lambda *_: 0.01)
    scheduler = ReminderScheduler(db, send, ZoneInfo("UTC"))
    await scheduler.set(1, 100, time(8, 0))
    await asyncio.sleep(0.1)
    await scheduler.stop()

    assert sent and sent[0][0] == 100
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


async def test_scheduler_uses_composed_message_and_can_skip(db, monkeypatch):
    sent: list[tuple[int, str, object]] = []

    async def send(chat_id: int, text: str, reply_markup=None) -> None:
        sent.append((chat_id, text, reply_markup))

    async def compose(user_id: int):
        return None if user_id == 2 else (f"hello {user_id}", "KB")

    monkeypatch.setattr("habit_bot.services.reminders.seconds_until", lambda *_: 0.01)
    scheduler = ReminderScheduler(db, send, ZoneInfo("UTC"), compose=compose)
    await scheduler.set(1, 100, time(8, 0))
    await scheduler.set(2, 200, time(8, 0))  # composer returns None: nothing to remind about
    await asyncio.sleep(0.1)
    await scheduler.stop()

    assert sent and all(item == (100, "hello 1", "KB") for item in sent)


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
