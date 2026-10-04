from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from habit_bot import keyboards as kb
from habit_bot import texts, views
from habit_bot.services.habits import AddResult, DoneResult, HabitService, HabitStats
from habit_bot.services.reminders import ReminderScheduler

router = Router(name="habits")


class AddHabit(StatesGroup):
    name = State()


def _parse_id(command: CommandObject) -> int | None:
    arg = (command.args or "").strip().lstrip("#")
    return int(arg) if arg.isdecimal() else None


async def _stat_for(habits: HabitService, user_id: int, habit_id: int) -> HabitStats | None:
    return next((s for s in await habits.stats(user_id) if s.habit.id == habit_id), None)


async def _send_view(
    message: Message, view: str, habits: HabitService, scheduler: ReminderScheduler
) -> None:
    if not message.from_user:
        return
    text, markup = await views.render(view, habits, scheduler, message.from_user.id)
    await message.answer(text, reply_markup=markup)


# --- views: commands and bottom-keyboard buttons ----------------------------------------------


@router.message(F.text == kb.BTN_TODAY)
@router.message(Command("today"))
async def show_today(message: Message, habits: HabitService, scheduler: ReminderScheduler) -> None:
    await _send_view(message, views.VIEW_TODAY, habits, scheduler)


@router.message(F.text == kb.BTN_LIST)
@router.message(Command("list"))
async def show_list(message: Message, habits: HabitService, scheduler: ReminderScheduler) -> None:
    await _send_view(message, views.VIEW_LIST, habits, scheduler)


@router.message(F.text == kb.BTN_STATS)
@router.message(Command("stats"))
async def show_stats(message: Message, habits: HabitService, scheduler: ReminderScheduler) -> None:
    await _send_view(message, views.VIEW_STATS, habits, scheduler)


# --- adding ----------------------------------------------------------------------------------


async def _create(message: Message, habits: HabitService, raw: str, state: FSMContext) -> None:
    """Try to add a habit; keeps the dialog open only when the name was invalid."""
    if not message.from_user:
        return
    result, habit = await habits.add(message.from_user.id, raw)
    if result is AddResult.OK and habit:
        await state.clear()
        await message.answer(texts.added(habit.name, habit.id), reply_markup=kb.added_kb(habit.id))
    elif result is AddResult.INVALID:
        await message.answer(texts.add_usage(), reply_markup=kb.cancel_kb())
    else:
        await state.clear()
        await message.answer(
            texts.limit_reached() if result is AddResult.LIMIT else texts.duplicate()
        )


async def _ask_name(message: Message, state: FSMContext) -> None:
    await state.set_state(AddHabit.name)
    await message.answer(texts.add_prompt(), reply_markup=kb.cancel_kb())


@router.message(F.text == kb.BTN_ADD)
async def btn_add(message: Message, state: FSMContext) -> None:
    await _ask_name(message, state)


@router.message(Command("add"))
async def cmd_add(
    message: Message, command: CommandObject, habits: HabitService, state: FSMContext
) -> None:
    if command.args and command.args.strip():
        await _create(message, habits, command.args, state)
    else:
        await _ask_name(message, state)


@router.message(AddHabit.name, F.text, ~F.text.startswith("/"))
async def got_name(message: Message, habits: HabitService, state: FSMContext) -> None:
    await _create(message, habits, message.text or "", state)


@router.callback_query(F.data == "add")
async def cb_add(callback: CallbackQuery, state: FSMContext) -> None:
    if isinstance(callback.message, Message):
        await _ask_name(callback.message, state)
    await views.safe_answer(callback)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    was_active = await state.get_state() is not None
    await state.clear()
    await message.answer(texts.cancelled() if was_active else "Нечего отменять 🙂")


@router.callback_query(F.data == "cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if isinstance(callback.message, Message):
        await views.edit_text_only(callback.message, texts.cancelled())
    await views.safe_answer(callback)


# --- marking done ----------------------------------------------------------------------------


@router.message(Command("done"))
async def cmd_done(
    message: Message,
    command: CommandObject,
    habits: HabitService,
    scheduler: ReminderScheduler,
) -> None:
    if not message.from_user:
        return
    if not (command.args or "").strip():  # no id: show the checklist with ✅ buttons
        await _send_view(message, views.VIEW_TODAY, habits, scheduler)
        return
    habit_id = _parse_id(command)
    if habit_id is None:
        await message.answer(texts.bad_id("done"))
        return
    user_id = message.from_user.id
    result, habit = await habits.done(user_id, habit_id)
    if result is DoneResult.NOT_FOUND or habit is None:
        await message.answer(texts.not_found())
    elif result is DoneResult.ALREADY:
        await message.answer(texts.already_done(habit.name), reply_markup=kb.after_done_kb())
    else:
        item = await _stat_for(habits, user_id, habit.id)
        text = texts.done_reply(item, habits.today()) if item else texts.already_done(habit.name)
        await message.answer(text, reply_markup=kb.after_done_kb())


@router.callback_query(F.data.startswith("done:"))
async def cb_done(
    callback: CallbackQuery, habits: HabitService, scheduler: ReminderScheduler
) -> None:
    """✅ under a habit: mark it and redraw the same screen in place."""
    try:
        _, raw_id, view = (callback.data or "").split(":")
        habit_id = int(raw_id)
    except ValueError:
        await views.safe_answer(callback)
        return
    user_id = callback.from_user.id
    result, habit = await habits.done(user_id, habit_id)
    if result is DoneResult.NOT_FOUND or habit is None:
        await views.safe_answer(
            callback, "Привычка не найдена — возможно, её уже удалили.", alert=True
        )
    else:
        toast = "Уже отмечено сегодня 👍"
        if result is DoneResult.OK and (item := await _stat_for(habits, user_id, habit.id)):
            toast = texts.done_toast(item)
        await views.safe_answer(callback, toast)
    if isinstance(callback.message, Message):
        view = view if view in views.VIEWS else views.VIEW_TODAY
        text, markup = await views.render(view, habits, scheduler, user_id)
        await views.edit_message(callback.message, text, markup)


# --- deleting (with confirmation) ------------------------------------------------------------


@router.message(Command("delete"))
async def cmd_delete(message: Message, command: CommandObject, habits: HabitService) -> None:
    if not message.from_user:
        return
    habit_id = _parse_id(command)
    if habit_id is None:
        await message.answer(texts.bad_id("delete"))
        return
    item = await _stat_for(habits, message.from_user.id, habit_id)
    if item is None:
        await message.answer(texts.not_found())
        return
    await message.answer(
        texts.confirm_delete(item), reply_markup=kb.confirm_delete_kb(item.habit.id)
    )


@router.callback_query(F.data.startswith("del:"))
async def cb_delete(callback: CallbackQuery, habits: HabitService) -> None:
    habit_id = int((callback.data or "del:0").split(":")[1] or 0)
    item = await _stat_for(habits, callback.from_user.id, habit_id)
    if item is None:
        await views.safe_answer(callback, "Привычка уже удалена.")
        return
    if isinstance(callback.message, Message):
        await views.edit_message(
            callback.message, texts.confirm_delete(item), kb.confirm_delete_kb(item.habit.id)
        )
    await views.safe_answer(callback)


@router.callback_query(F.data.startswith("delok:"))
async def cb_delete_confirmed(
    callback: CallbackQuery, habits: HabitService, scheduler: ReminderScheduler
) -> None:
    habit_id = int((callback.data or "delok:0").split(":")[1] or 0)
    user_id = callback.from_user.id
    habit = await habits.get(user_id, habit_id)
    deleted = await habits.delete(user_id, habit_id)
    await views.safe_answer(callback, "🗑 Удалено" if deleted else "Привычка уже удалена.")
    if isinstance(callback.message, Message):
        text, markup = await views.render(views.VIEW_LIST, habits, scheduler, user_id)
        if deleted and habit:
            text = f"{texts.deleted(habit.name)}\n\n{text}"
        await views.edit_message(callback.message, text, markup)
