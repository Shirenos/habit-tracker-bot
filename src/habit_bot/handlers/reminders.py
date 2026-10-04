from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from habit_bot import keyboards as kb
from habit_bot import texts, views
from habit_bot.services.habits import HabitService
from habit_bot.services.reminders import ReminderScheduler, parse_hhmm

router = Router(name="reminders")


@router.message(F.text == kb.BTN_REMIND)
async def show_reminders(
    message: Message, habits: HabitService, scheduler: ReminderScheduler
) -> None:
    if not message.from_user:
        return
    text, markup = await views.render(views.VIEW_REMINDERS, habits, scheduler, message.from_user.id)
    await message.answer(text, reply_markup=markup)


@router.message(Command("remind"))
async def cmd_remind(
    message: Message,
    command: CommandObject,
    habits: HabitService,
    scheduler: ReminderScheduler,
) -> None:
    if not message.from_user:
        return
    arg = (command.args or "").strip().lower()
    if not arg:  # no argument: open the reminder panel
        await show_reminders(message, habits, scheduler)
        return
    if arg in {"off", "stop", "cancel", "выкл"}:
        removed = await scheduler.clear(message.from_user.id)
        await message.answer(texts.reminder_off(removed))
        return

    at = parse_hhmm(arg)
    if at is None:
        await message.answer(texts.reminder_usage())
        return
    await scheduler.set(message.from_user.id, message.chat.id, at)
    await message.answer(texts.reminder_set(at))


@router.callback_query(F.data.startswith("rem:"))
async def cb_remind(
    callback: CallbackQuery, habits: HabitService, scheduler: ReminderScheduler
) -> None:
    """Preset buttons: set the reminder time (or switch it off) and redraw the panel."""
    value = (callback.data or "").split(":", 1)[1]
    user_id = callback.from_user.id
    if value == "off":
        await scheduler.clear(user_id)
        toast = "🔕 Напоминание выключено"
    elif (at := parse_hhmm(value)) is not None and isinstance(callback.message, Message):
        await scheduler.set(user_id, callback.message.chat.id, at)
        toast = f"⏰ Напомню в {at:%H:%M}"
    else:
        await views.safe_answer(callback)
        return
    await views.safe_answer(callback, toast)
    if isinstance(callback.message, Message):
        text, markup = await views.render(views.VIEW_REMINDERS, habits, scheduler, user_id)
        await views.edit_message(callback.message, text, markup)
