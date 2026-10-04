from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from habit_bot import keyboards as kb
from habit_bot import texts, views
from habit_bot.services.habits import HabitService
from habit_bot.services.reminders import ReminderScheduler

router = Router(name="basic")


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    name = message.from_user.first_name if message.from_user else None
    await message.answer(texts.welcome(name), reply_markup=kb.main_menu())


@router.message(Command("menu"))
async def cmd_menu(message: Message) -> None:
    await message.answer(texts.menu_text(), reply_markup=kb.main_menu())


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(texts.HELP_TEXT, reply_markup=kb.help_kb())


@router.message(F.text == kb.BTN_SETTINGS)
@router.message(Command("settings"))
async def show_settings(
    message: Message, habits: HabitService, scheduler: ReminderScheduler
) -> None:
    if not message.from_user:
        return
    text, markup = await views.render(views.VIEW_SETTINGS, habits, scheduler, message.from_user.id)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith("v:"))
async def cb_view(
    callback: CallbackQuery, habits: HabitService, scheduler: ReminderScheduler
) -> None:
    """Open / refresh any screen by editing the message in place."""
    view = (callback.data or "").split(":", 1)[1]
    if not isinstance(callback.message, Message) or view not in views.VIEWS:
        await views.safe_answer(callback)
        return
    text, markup = await views.render(view, habits, scheduler, callback.from_user.id)
    changed = await views.edit_message(callback.message, text, markup)
    await views.safe_answer(callback, None if changed else "Всё актуально ✨")


@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery) -> None:
    await views.safe_answer(callback, "Уже отмечено сегодня 👍")
