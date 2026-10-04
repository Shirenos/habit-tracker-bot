"""Entry point: wires config, database, services and the aiogram dispatcher."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError

from habit_bot.config import ConfigError, load_settings
from habit_bot.db import Database
from habit_bot.handlers import build_router
from habit_bot.profile import apply_commands
from habit_bot.services.habits import HabitService
from habit_bot.services.reminders import ReminderScheduler
from habit_bot.views import reminder_composer

logger = logging.getLogger(__name__)


async def main() -> None:
    settings = load_settings()
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    db = Database(settings.database_path)
    await db.connect()

    try:
        bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        try:
            habits = HabitService(db, settings.timezone)
            scheduler = ReminderScheduler(
                db, bot.send_message, settings.timezone, compose=reminder_composer(habits)
            )
            try:
                await scheduler.start()

                dp = Dispatcher(habits=habits, scheduler=scheduler, admin_ids=settings.admin_ids)
                dp.include_router(build_router())

                try:  # cheap and idempotent; name/descriptions: `python -m habit_bot.profile`
                    await apply_commands(bot)
                except TelegramAPIError:
                    logger.warning("Could not refresh the command list", exc_info=True)

                logger.info("Bot started")
                await dp.start_polling(bot)
            finally:
                await scheduler.stop()
        finally:
            await bot.session.close()
    finally:
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
