import pytest
from aiogram.client.session.aiohttp import AiohttpSession

from habit_bot import main as main_module
from habit_bot.config import Settings
from habit_bot.db import Database
from habit_bot.handlers import admin, basic, fallback, habits, reminders
from habit_bot.services.reminders import ReminderScheduler


@pytest.mark.parametrize("failing_step", ["start", "polling"])
async def test_main_always_closes_db_and_bot_session(tmp_path, monkeypatch, failing_step):
    from zoneinfo import ZoneInfo

    settings = Settings(
        bot_token="123456:TEST-TOKEN", database_path=tmp_path / "t.db", timezone=ZoneInfo("UTC")
    )
    monkeypatch.setattr(main_module, "load_settings", lambda: settings)
    closed: list[str] = []

    real_db_close = Database.close
    real_session_close = AiohttpSession.close

    async def db_close(self):
        closed.append("db")
        await real_db_close(self)

    async def session_close(self):
        closed.append("session")
        await real_session_close(self)

    async def stop(self):
        closed.append("scheduler")

    async def failing_start(self):
        raise RuntimeError("start failed")

    async def failing_polling(self, bot, **kwargs):
        raise RuntimeError("polling failed")

    async def noop_commands(bot):
        return None

    # Feature routers are module-level singletons; detach them so a fresh tree can be built.
    for module in (admin, basic, fallback, habits, reminders):
        module.router._parent_router = None

    monkeypatch.setattr(Database, "close", db_close)
    monkeypatch.setattr(AiohttpSession, "close", session_close)
    monkeypatch.setattr(ReminderScheduler, "stop", stop)
    monkeypatch.setattr(main_module, "apply_commands", noop_commands)
    if failing_step == "start":
        monkeypatch.setattr(ReminderScheduler, "start", failing_start)
    else:
        monkeypatch.setattr(main_module.Dispatcher, "start_polling", failing_polling)

    with pytest.raises(RuntimeError, match="failed"):
        await main_module.main()

    assert closed == ["scheduler", "session", "db"]
