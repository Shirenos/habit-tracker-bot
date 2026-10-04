"""Screens of the bot: each view is a ``(text, inline keyboard)`` pair that can be sent as a new
message or used to edit an existing one in place."""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Awaitable, Callable

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from habit_bot import keyboards as kb
from habit_bot import texts
from habit_bot.services.habits import HabitService
from habit_bot.services.reminders import ReminderScheduler

logger = logging.getLogger(__name__)

Rendered = tuple[str, InlineKeyboardMarkup]

VIEW_TODAY = "t"
VIEW_LIST = "l"
VIEW_STATS = "s"
VIEW_REMINDERS = "r"
VIEW_SETTINGS = "g"
VIEW_HELP = "h"
VIEWS = frozenset({VIEW_TODAY, VIEW_LIST, VIEW_STATS, VIEW_REMINDERS, VIEW_SETTINGS, VIEW_HELP})


async def render(
    view: str, habits: HabitService, scheduler: ReminderScheduler, user_id: int
) -> Rendered:
    """Build the screen ``view`` for ``user_id``. Unknown views fall back to *today*."""
    today = habits.today()
    if view == VIEW_HELP:
        return texts.HELP_TEXT, kb.help_kb()
    if view == VIEW_REMINDERS:
        at = await scheduler.get(user_id)
        return texts.reminders_view(at), kb.reminders_kb(f"{at:%H:%M}" if at else None)

    stats = await habits.stats(user_id, today)
    if view == VIEW_SETTINGS:
        at = await scheduler.get(user_id)
        return (
            texts.settings_view(len(stats), at, str(habits.timezone)),
            kb.settings_kb(),
        )
    if not stats:
        text = {
            VIEW_LIST: texts.empty_state(),
            VIEW_STATS: texts.stats_view(stats, today),
        }.get(view, texts.empty_state())
        return text, kb.empty_kb()
    if view == VIEW_LIST:
        return texts.list_view(stats), kb.list_kb(stats)
    if view == VIEW_STATS:
        return texts.stats_view(stats, today), kb.stats_kb()
    return texts.today_view(stats, today), kb.today_kb(stats)


def reminder_composer(
    habits: HabitService,
) -> Callable[[int], Awaitable[tuple[str, InlineKeyboardMarkup] | None]]:
    """Reminder content: today's open habits with ✅ buttons; ``None`` if there is nothing to do."""

    async def compose(user_id: int) -> tuple[str, InlineKeyboardMarkup] | None:
        today = habits.today()
        stats = await habits.stats(user_id, today)
        if not stats or all(s.done_today for s in stats):
            return None
        return texts.today_view(stats, today, reminder=True), kb.today_kb(stats)

    return compose


async def edit_message(message: Message, text: str, markup: InlineKeyboardMarkup) -> bool:
    """Edit in place. Returns False when Telegram says nothing changed."""
    try:
        await message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc):
            return False
        raise
    return True


async def safe_answer(
    callback: CallbackQuery, text: str | None = None, *, alert: bool = False
) -> None:
    """``answerCallbackQuery`` that never raises (e.g. when the query is too old)."""
    with contextlib.suppress(TelegramBadRequest):
        await callback.answer(text, show_alert=alert)


async def edit_text_only(message: Message, text: str) -> None:
    """Replace a message with plain text and drop its inline keyboard."""
    with contextlib.suppress(TelegramBadRequest):
        await message.edit_text(text, reply_markup=None)
