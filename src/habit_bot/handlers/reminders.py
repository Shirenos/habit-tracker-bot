from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from habit_bot.services.reminders import ReminderScheduler, parse_hhmm

router = Router(name="reminders")


@router.message(Command("remind"))
async def cmd_remind(
    message: Message, command: CommandObject, scheduler: ReminderScheduler
) -> None:
    if not message.from_user:
        return
    arg = (command.args or "").strip().lower()
    if arg in {"off", "stop", "cancel"}:
        removed = await scheduler.clear(message.from_user.id)
        await message.answer("🔕 Reminder disabled." if removed else "You have no reminder set.")
        return

    at = parse_hhmm(arg)
    if at is None:
        await message.answer(
            "Usage: <code>/remind HH:MM</code> (24h), e.g. <code>/remind 21:30</code>\n"
            "Disable with <code>/remind off</code>."
        )
        return
    await scheduler.set(message.from_user.id, message.chat.id, at)
    await message.answer(f"⏰ Daily reminder set for <b>{at:%H:%M}</b>.")
