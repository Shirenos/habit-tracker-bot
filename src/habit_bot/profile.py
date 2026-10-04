"""Bot profile (name, descriptions, command list, menu button) applied through the Bot API.

Run ``python -m habit_bot.profile`` once after changing the texts below. The token is read from
``BOT_TOKEN`` (env / ``.env``) and is never printed.

Telegram rate-limits ``setMyName`` strictly, so the name and descriptions are *not* touched on
every bot start; only the cheap command list and menu button are refreshed by
:func:`apply_commands`.

The Bot API cannot set the bot's photo: upload ``docs/avatar.png`` manually via
@BotFather → ``/setuserpic``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand, BotCommandScopeDefault, MenuButtonCommands

from habit_bot.config import ConfigError, load_settings

BOT_NAME = "Трекер привычек 🌱"  # <= 64 characters

SHORT_DESCRIPTION = (  # <= 120 characters
    "Трекер привычек: отмечайте дела одним нажатием, растите серии 🔥 и смотрите статистику недели."
)

DESCRIPTION = (  # <= 512 characters, shown on the empty chat screen
    "🌱 Трекер привычек в Telegram\n\n"
    "✅ Отмечайте привычки одним нажатием\n"
    "🔥 Серии и рекорды — не теряйте темп\n"
    "📊 Статистика и график недели\n"
    "🔔 Ежедневные напоминания в удобное время\n\n"
    "Нажмите «Начать» и добавьте первую привычку: /add Пить воду"
)

BOT_COMMANDS = [
    BotCommand(command="today", description="📅 Привычки на сегодня"),
    BotCommand(command="add", description="➕ Добавить привычку"),
    BotCommand(command="list", description="📋 Все привычки"),
    BotCommand(command="done", description="✅ Отметить выполненной"),
    BotCommand(command="stats", description="📊 Статистика и серии"),
    BotCommand(command="remind", description="🔔 Ежедневное напоминание"),
    BotCommand(command="delete", description="🗑 Удалить привычку"),
    BotCommand(command="menu", description="📱 Показать меню"),
    BotCommand(command="help", description="❓ Справка"),
]


async def apply_commands(bot: Bot) -> None:
    """Command list (default scope) and the "commands" menu button; cheap, safe at every start."""
    await bot.set_my_commands(BOT_COMMANDS, scope=BotCommandScopeDefault())
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())


async def apply_profile(bot: Bot) -> list[str]:
    """Set name, descriptions, commands and menu button. Returns a list of failure messages."""
    steps: dict[str, Callable[[], Awaitable[bool]]] = {
        "name": lambda: bot.set_my_name(name=BOT_NAME),
        "description": lambda: bot.set_my_description(description=DESCRIPTION),
        "short description": lambda: bot.set_my_short_description(
            short_description=SHORT_DESCRIPTION
        ),
        "commands": lambda: bot.set_my_commands(BOT_COMMANDS, scope=BotCommandScopeDefault()),
        "menu button": lambda: bot.set_chat_menu_button(menu_button=MenuButtonCommands()),
    }
    failures = []
    for title, call in steps.items():
        try:
            await call()
            print(f"✓ {title}")
        except TelegramAPIError as exc:
            failures.append(f"{title}: {exc.message}")
            print(f"✗ {title}: {exc.message}")
    return failures


async def _main() -> int:
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"Configuration error: {exc}")
        return 2
    bot = Bot(settings.bot_token)
    try:
        failures = await apply_profile(bot)
    finally:
        await bot.session.close()
    return 1 if failures else 0


def run() -> None:
    raise SystemExit(asyncio.run(_main()))


if __name__ == "__main__":
    run()
