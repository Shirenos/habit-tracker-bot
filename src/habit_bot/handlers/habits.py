from html import escape

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from habit_bot.services.habits import (
    MAX_HABITS_PER_USER,
    MAX_NAME_LENGTH,
    AddResult,
    DoneResult,
    HabitService,
    HabitStats,
)

router = Router(name="habits")


def _parse_id(command: CommandObject) -> int | None:
    arg = (command.args or "").strip().lstrip("#")
    return int(arg) if arg.isdecimal() else None


def format_stats(item: HabitStats) -> str:
    strip = "".join("🟩" if done else "⬜" for _, done in item.week)
    return (
        f"<b>#{item.habit.id} {escape(item.habit.name)}</b>\n"
        f"{strip}\n"
        f"🔥 Current: {item.current}  🏆 Best: {item.longest}  ✅ Total: {item.total}"
    )


@router.message(Command("add"))
async def cmd_add(message: Message, command: CommandObject, habits: HabitService) -> None:
    if not message.from_user:
        return
    result, habit = await habits.add(message.from_user.id, command.args or "")
    replies = {
        AddResult.INVALID: (
            f"Usage: <code>/add &lt;habit&gt;</code> (up to {MAX_NAME_LENGTH} chars)"
        ),
        AddResult.LIMIT: f"You can track at most {MAX_HABITS_PER_USER} habits. Delete one first.",
        AddResult.DUPLICATE: "You already have a habit with that name.",
    }
    if result is AddResult.OK and habit:
        await message.answer(
            f"✅ Added <b>{escape(habit.name)}</b> (id <code>{habit.id}</code>).\n"
            f"Mark it with <code>/done {habit.id}</code>."
        )
    else:
        await message.answer(replies[result])


@router.message(Command("list"))
async def cmd_list(message: Message, habits: HabitService) -> None:
    if not message.from_user:
        return
    items = await habits.list(message.from_user.id)
    if not items:
        await message.answer("No habits yet. Add one with <code>/add Read 20 pages</code>.")
        return
    lines = [
        f"{'✅' if done else '⬜'} <code>{h.id}</code> — {escape(h.name)}" for h, done in items
    ]
    await message.answer("<b>Your habits</b> (today)\n" + "\n".join(lines))


@router.message(Command("done"))
async def cmd_done(message: Message, command: CommandObject, habits: HabitService) -> None:
    if not message.from_user:
        return
    habit_id = _parse_id(command)
    if habit_id is None:
        await message.answer("Usage: <code>/done &lt;id&gt;</code> — see ids in /list")
        return
    result, habit = await habits.done(message.from_user.id, habit_id)
    if result is DoneResult.NOT_FOUND or habit is None:
        await message.answer("I can't find a habit with that id. Check /list.")
    elif result is DoneResult.ALREADY:
        await message.answer(f"You already did <b>{escape(habit.name)}</b> today 👍")
    else:
        stats = next(s for s in await habits.stats(message.from_user.id) if s.habit.id == habit.id)
        await message.answer(
            f"🎉 Nice! <b>{escape(habit.name)}</b> done. Streak: 🔥 {stats.current}"
        )


@router.message(Command("delete"))
async def cmd_delete(message: Message, command: CommandObject, habits: HabitService) -> None:
    if not message.from_user:
        return
    habit_id = _parse_id(command)
    if habit_id is None:
        await message.answer("Usage: <code>/delete &lt;id&gt;</code> — see ids in /list")
        return
    deleted = await habits.delete(message.from_user.id, habit_id)
    await message.answer("🗑 Habit deleted." if deleted else "I can't find a habit with that id.")


@router.message(Command("stats"))
async def cmd_stats(message: Message, habits: HabitService) -> None:
    if not message.from_user:
        return
    stats = await habits.stats(message.from_user.id)
    if not stats:
        await message.answer("Nothing to show yet. Add a habit with /add.")
        return
    await message.answer("📊 <b>Last 7 days</b>\n\n" + "\n\n".join(format_stats(s) for s in stats))
