"""Admin-only ``/admin`` command with usage statistics.

Admins are Telegram user IDs listed in the ``ADMIN_IDS`` environment variable. Everyone else is
ignored silently: the command gets no reply, so its existence is not revealed.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import BaseFilter, Command
from aiogram.types import Message

from habit_bot import texts
from habit_bot.services.habits import HabitService

router = Router(name="admin")


class IsAdmin(BaseFilter):
    """Passes only for messages sent by a user whose ID is in ``admin_ids``."""

    async def __call__(self, message: Message, admin_ids: frozenset[int] = frozenset()) -> bool:
        return message.from_user is not None and message.from_user.id in admin_ids


@router.message(Command("admin"), IsAdmin())
async def cmd_admin(message: Message, habits: HabitService) -> None:
    await message.answer(texts.admin_panel(await habits.admin_stats()))


@router.message(Command("admin"))
async def cmd_admin_denied(message: Message) -> None:
    """Swallow ``/admin`` from non-admins without any reply."""
