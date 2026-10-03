"""Entry point: wires config, database, services and the aiogram dispatcher."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from habit_bot.config import ConfigError, load_settings
from habit_bot.db import Database
from habit_bot.handlers import build_router
from habit_bot.services.habits import HabitService
from habit_bot.services.reminders import ReminderScheduler

logger = logging.getLogger(__name__)


async def main() -> None:
    settings = load_settings()
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    db = Database(settings.database_path)
    await db.connect()

    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    scheduler = ReminderScheduler(db, bot.send_message, settings.timezone)
    await scheduler.start()

    dp = Dispatcher(habits=HabitService(db, settings.timezone), scheduler=scheduler)
    dp.include_router(build_router())

    try:
        logger.info("Bot started")
        await dp.start_polling(bot)
    finally:
        await scheduler.stop()
        await bot.session.close()
        await db.close()


def run() -> None:
    try:
        asyncio.run(main())
    except ConfigError as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc
    except KeyboardInterrupt:
        logger.info("Bot stopped")


if __name__ == "__main__":
    run()
