"""Reply (bottom) and inline keyboards plus the callback-data scheme.

Callback data (all ≤ 64 bytes):

* ``v:<view>``        – show a view in place; views: ``t`` today, ``l`` list, ``s`` stats,
  ``r`` reminders, ``g`` settings, ``h`` help. Also used by the 🔄 button.
* ``done:<id>:<view>``– mark habit done, then re-render ``<view>``.
* ``del:<id>``        – ask for confirmation; ``delok:<id>`` performs the deletion.
* ``rem:<HH:MM|off>`` – set / disable the daily reminder.
* ``add`` / ``cancel`` / ``noop``.
"""

from __future__ import annotations

from collections.abc import Sequence

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from habit_bot.services.habits import HabitStats

BTN_TODAY = "📅 Сегодня"
BTN_ADD = "➕ Добавить"
BTN_LIST = "📋 Список"
BTN_STATS = "📊 Статистика"
BTN_REMIND = "🔔 Напоминания"
BTN_SETTINGS = "⚙️ Настройки"

MENU_BUTTONS = (BTN_TODAY, BTN_ADD, BTN_LIST, BTN_STATS, BTN_REMIND, BTN_SETTINGS)
MENU_PLACEHOLDER = "Выберите действие или напишите /add название…"

REMINDER_PRESETS = ("08:00", "12:00", "18:00", "21:00")


def main_menu() -> ReplyKeyboardMarkup:
    """Persistent bottom keyboard with the everyday actions."""
    rows = [
        [BTN_TODAY, BTN_ADD],
        [BTN_LIST, BTN_STATS],
        [BTN_REMIND, BTN_SETTINGS],
    ]
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=text) for text in row] for row in rows],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder=MENU_PLACEHOLDER,
    )


def _short(name: str, limit: int = 28) -> str:
    return name if len(name) <= limit else name[: limit - 1] + "…"


def refresh_button(view: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text="🔄 Обновить", callback_data=f"v:{view}")


def today_kb(stats: Sequence[HabitStats]) -> InlineKeyboardMarkup:
    """One ✅ button per habit that is still open today, plus navigation."""
    builder = InlineKeyboardBuilder()
    for s in stats:
        if not s.done_today:
            builder.row(
                InlineKeyboardButton(
                    text=f"✅ {_short(s.habit.name)}", callback_data=f"done:{s.habit.id}:t"
                )
            )
    builder.row(
        refresh_button("t"),
        InlineKeyboardButton(text="📋 Список", callback_data="v:l"),
        InlineKeyboardButton(text="📊 Статистика", callback_data="v:s"),
    )
    return builder.as_markup()


def list_kb(stats: Sequence[HabitStats]) -> InlineKeyboardMarkup:
    """Per habit: ✅ mark done (or ✔️ when already done) and 🗑 delete."""
    builder = InlineKeyboardBuilder()
    for s in stats:
        if s.done_today:
            first = InlineKeyboardButton(text=f"✔️ {_short(s.habit.name, 22)}", callback_data="noop")
        else:
            first = InlineKeyboardButton(
                text=f"✅ {_short(s.habit.name, 22)}", callback_data=f"done:{s.habit.id}:l"
            )
        builder.row(first, InlineKeyboardButton(text="🗑", callback_data=f"del:{s.habit.id}"))
    builder.row(
        refresh_button("l"),
        InlineKeyboardButton(text="➕ Добавить", callback_data="add"),
        InlineKeyboardButton(text="📅 Сегодня", callback_data="v:t"),
    )
    return builder.as_markup()


def stats_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        refresh_button("s"),
        InlineKeyboardButton(text="📅 Сегодня", callback_data="v:t"),
        InlineKeyboardButton(text="📋 Список", callback_data="v:l"),
    )
    return builder.as_markup()


def empty_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить привычку", callback_data="add")
    return builder.as_markup()


def confirm_delete_kb(habit_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🗑 Да, удалить", callback_data=f"delok:{habit_id}")
    builder.button(text="↩️ Отмена", callback_data="v:l")
    builder.adjust(2)
    return builder.as_markup()


def added_kb(habit_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Отметить сегодня", callback_data=f"done:{habit_id}:t")
    builder.button(text="📋 Список", callback_data="v:l")
    builder.adjust(1, 1)
    return builder.as_markup()


def after_done_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📅 Сегодня", callback_data="v:t")
    builder.button(text="📊 Статистика", callback_data="v:s")
    builder.adjust(2)
    return builder.as_markup()


def cancel_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✖️ Отмена", callback_data="cancel")
    return builder.as_markup()


def reminders_kb(current: str | None) -> InlineKeyboardMarkup:
    """Preset times (the active one is marked ✔️) and a switch-off button."""
    builder = InlineKeyboardBuilder()
    for preset in REMINDER_PRESETS:
        mark = "✔️ " if preset == current else "🕘 "
        builder.button(text=f"{mark}{preset}", callback_data=f"rem:{preset}")
    builder.adjust(2, 2)
    builder.row(InlineKeyboardButton(text="🔕 Выключить", callback_data="rem:off"))
    builder.row(InlineKeyboardButton(text="⚙️ Настройки", callback_data="v:g"))
    return builder.as_markup()


def settings_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔔 Напоминания", callback_data="v:r")
    builder.button(text="❓ Справка", callback_data="v:h")
    builder.button(text="📋 Список", callback_data="v:l")
    builder.adjust(2, 1)
    return builder.as_markup()


def help_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📅 Сегодня", callback_data="v:t")
    builder.button(text="⚙️ Настройки", callback_data="v:g")
    builder.adjust(2)
    return builder.as_markup()
