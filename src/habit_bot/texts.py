"""Russian texts and Telegram-HTML formatting. Pure functions: no I/O, easy to test.

Every piece of user-supplied text (habit names, first names) goes through :func:`html.escape`.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, time
from html import escape

from habit_bot.services.habits import MAX_HABITS_PER_USER, MAX_NAME_LENGTH, HabitStats

SEP = "━━━━━━━━━━━━━━━"

WEEKDAYS_SHORT = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
WEEKDAYS_FULL = (
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
)
MONTHS_GEN = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)

MILESTONES = (3, 7, 14, 30, 60, 100, 200, 365)

PHRASES_NONE = (
    "Первый шаг — самый важный. Начните с самой простой привычки 🌱",
    "Маленькое действие сегодня — большая привычка завтра 💫",
    "Не нужно идеально — нужно начать 🚀",
)
PHRASES_SOME = (
    "Отличный темп! Осталось совсем чуть-чуть 💪",
    "Вы уже в игре — добивайте день! 🎯",
    "Каждая отметка — кирпичик вашей серии 🧱",
)
PHRASES_ALL = (
    "Все привычки на сегодня выполнены! Вы великолепны 🏆",
    "Идеальный день! Заслуженно можно отдыхать 🌟",
    "100% — так держать! Серии растут 🔥",
)
PHRASES_DONE = (
    "Так держать!",
    "Отличная работа!",
    "Ещё один шаг к цели!",
    "Вот это дисциплина!",
)

IDEAS = "💧 Пить воду · 📖 Читать 20 минут · 🏃 Зарядка · 🧘 Медитация"

HELP_TEXT = (
    f"❓ <b>Справка</b>\n{SEP}\n\n"
    "Привычки — это просто: добавьте, отмечайте каждый день и растите серию 🔥\n\n"
    "<b>Команды</b>\n"
    "/today — привычки на сегодня\n"
    "/add <i>название</i> — добавить привычку\n"
    "/list — все привычки\n"
    "/done <i>номер</i> — отметить выполненной\n"
    "/stats — статистика и график недели\n"
    "/remind <i>ЧЧ:ММ</i> — ежедневное напоминание (<code>/remind off</code> — выключить)\n"
    "/delete <i>номер</i> — удалить привычку\n"
    "/menu — показать меню\n"
    "/help — эта справка\n\n"
    "💡 Номер привычки указан рядом с её названием: <code>#1</code>."
)


# --- helpers ----------------------------------------------------------------------------------


def plural(n: int, one: str, few: str, many: str) -> str:
    """Russian plural form for ``n``: 1 день, 2 дня, 5 дней."""
    n = abs(n)
    if 11 <= n % 100 <= 14:
        return many
    last = n % 10
    if last == 1:
        return one
    if 2 <= last <= 4:
        return few
    return many


def days_word(n: int) -> str:
    return f"{n} {plural(n, 'день', 'дня', 'дней')}"


def bar(done: int, total: int, width: int = 5) -> str:
    """Progress bar such as ``▰▰▰▱▱``. Never looks full/empty unless it really is."""
    if total <= 0:
        return "▱" * width
    filled = round(done / total * width)
    if 0 < done < total:
        filled = min(max(filled, 1), width - 1)
    return "▰" * filled + "▱" * (width - filled)


def percent(done: int, total: int) -> int:
    return round(done * 100 / total) if total else 0


def date_phrase(day: date) -> str:
    return f"{WEEKDAYS_FULL[day.weekday()].capitalize()}, {day.day} {MONTHS_GEN[day.month - 1]}"


def short_range(start: date, end: date) -> str:
    if start.month == end.month:
        return f"{start.day} – {end.day} {MONTHS_GEN[end.month - 1]}"
    return f"{start.day} {MONTHS_GEN[start.month - 1]} – {end.day} {MONTHS_GEN[end.month - 1]}"


def pick(options: Sequence[str], today: date, salt: int = 0) -> str:
    """Deterministic 'random' phrase: stable within a day, varies across days."""
    return options[(today.toordinal() + salt) % len(options)]


def day_phrase(done: int, total: int, today: date) -> str:
    if done >= total:
        return pick(PHRASES_ALL, today)
    if done == 0:
        return pick(PHRASES_NONE, today)
    return pick(PHRASES_SOME, today, done)


def streak_label(current: int) -> str:
    return f"🔥 {days_word(current)}" if current else "🌱 серия впереди"


def next_milestone(current: int) -> int | None:
    return next((m for m in MILESTONES if m > current), None)


# --- cards ------------------------------------------------------------------------------------


COMPACT_FROM = 13  # with this many habits cards shrink to one line to fit Telegram's 4096 limit


def habit_card(item: HabitStats, *, compact: bool = False) -> str:
    """Two-line card: status icon + name + id, then streak and the last-7-days bar."""
    week_done = sum(done for _, done in item.week)
    icon = "✅" if item.done_today else "⬜"
    if compact:
        streak = f" · 🔥 {item.current}" if item.current else ""
        return f"{icon} <b>{escape(item.habit.name)}</b>  <code>#{item.habit.id}</code>{streak}"
    return (
        f"{icon} <b>{escape(item.habit.name)}</b>  <code>#{item.habit.id}</code>\n"
        f"└ {streak_label(item.current)} · {bar(week_done, 7, 7)} {week_done}/7"
    )


def cards_block(stats: Sequence[HabitStats]) -> str:
    compact = len(stats) >= COMPACT_FROM
    return ("\n" if compact else "\n\n").join(habit_card(s, compact=compact) for s in stats)


def empty_state() -> str:
    return (
        f"🌱 <b>Пока нет привычек</b>\n{SEP}\n\n"
        "Начните с малого — одна привычка уже запускает перемены.\n\n"
        "Нажмите «➕ Добавить» или отправьте, например:\n"
        "<code>/add Пить воду</code>\n\n"
        f"Идеи: {IDEAS}"
    )


def today_view(stats: Sequence[HabitStats], today: date, *, reminder: bool = False) -> str:
    if not stats:
        return empty_state()
    done = sum(s.done_today for s in stats)
    total = len(stats)
    title = "⏰ <b>Время для привычек!</b>" if reminder else "📅 <b>Сегодня</b>"
    head = f"{title}\n<i>{date_phrase(today)}</i>\n{SEP}\n\n"
    progress = f"{bar(done, total)} <b>{done}/{total}</b> · {percent(done, total)}%"
    cards = cards_block(stats)
    return f"{head}{progress}\n\n{cards}\n\n💬 <i>{day_phrase(done, total, today)}</i>"


def list_view(stats: Sequence[HabitStats]) -> str:
    if not stats:
        return empty_state()
    done = sum(s.done_today for s in stats)
    head = (
        f"📋 <b>Мои привычки</b>  <i>{len(stats)} из {MAX_HABITS_PER_USER}</i>\n{SEP}\n\n"
        f"Сегодня: {bar(done, len(stats))} <b>{done}/{len(stats)}</b>\n\n"
    )
    return head + cards_block(stats)


def week_chart(stats: Sequence[HabitStats], today: date) -> str:
    """Text bar chart: for each of the last 7 days, how many habits were done."""
    total = len(stats)
    if not total:
        return ""
    rows = []
    for i, (day, _) in enumerate(stats[0].week):
        done = sum(s.week[i][1] for s in stats)
        mark = "  ← сегодня" if day == today else ""
        counts = f"{done}/{total}".ljust(len(str(total)) * 2 + 1)
        rows.append(
            f"{WEEKDAYS_SHORT[day.weekday()]} {day.day:>2} {bar(done, total)} {counts}{mark}"
        )
    return "\n".join(rows)


def stats_view(stats: Sequence[HabitStats], today: date) -> str:
    if not stats:
        return (
            f"📊 <b>Статистика</b>\n{SEP}\n\n"
            "Пока считать нечего — добавьте первую привычку 🌱\n"
            "Например: <code>/add Пить воду</code>"
        )
    total = len(stats)
    first, last = stats[0].week[0][0], stats[0].week[-1][0]
    week_done = sum(done for s in stats for _, done in s.week)
    week_total = total * len(stats[0].week)
    best = max(stats, key=lambda s: (s.current, s.longest))

    summary = [
        f"✨ Выполнено <b>{week_done} из {week_total}</b> · {percent(week_done, week_total)}%",
    ]
    if best.current:
        summary.append(
            f"🔥 Лучшая серия: <b>{escape(best.habit.name)}</b> — {days_word(best.current)}"
        )
    blocks = []
    for s in stats:
        strip = "".join("🟩" if done else "⬜" for _, done in s.week)
        icon = "✅" if s.done_today else "⬜"
        facts = f"{streak_label(s.current)} · 🏆 рекорд {s.longest} · всего {s.total}"
        if len(stats) >= COMPACT_FROM:
            blocks.append(f"{icon} <b>{escape(s.habit.name)}</b> · {strip}")
        else:
            blocks.append(f"{icon} <b>{escape(s.habit.name)}</b>\n{strip}\n{facts}")
    return (
        f"📊 <b>Статистика</b>\n{SEP}\n\n"
        f"<b>Неделя</b> · {short_range(first, last)}\n"
        f"<pre>{week_chart(stats, today)}</pre>\n"
        + "\n".join(summary)
        + "\n\n<b>По привычкам</b>\n\n"
        + ("\n" if len(stats) >= COMPACT_FROM else "\n\n").join(blocks)
        + f"\n\n💬 <i>{stats_phrase(week_done, week_total, today)}</i>"
    )


def stats_phrase(done: int, total: int, today: date) -> str:
    share = percent(done, total)
    if share >= 80:
        return "Вы в потрясающей форме! Так держать 🏆"
    if share >= 50:
        return "Хороший ритм — ещё немного, и привычка закрепится 💪"
    if share > 0:
        return "Начало положено. Главное — регулярность, а не идеальность 🌱"
    return pick(PHRASES_NONE, today)


# --- action replies ---------------------------------------------------------------------------


def added(name: str, habit_id: int) -> str:
    return (
        f"✅ <b>Привычка добавлена!</b>\n{SEP}\n\n"
        f"⬜ <b>{escape(name)}</b>  <code>#{habit_id}</code>\n\n"
        "Отметьте её сегодня — и серия 🔥 начнётся!"
    )


def done_reply(item: HabitStats, today: date) -> str:
    text = (
        f"🎉 <b>{pick(PHRASES_DONE, today, item.habit.id)}</b>\n{SEP}\n\n"
        f"✅ <b>{escape(item.habit.name)}</b> — выполнено\n"
        f"{streak_label(item.current)}"
    )
    if item.current == item.longest and item.current > 1:
        text += " · 🏆 новый рекорд!"
    nxt = next_milestone(item.current)
    if nxt:
        text += f"\n🎯 До {days_word(nxt)}: {bar(item.current, nxt, 7)} {item.current}/{nxt}"
    return text


def done_toast(item: HabitStats) -> str:
    return f"🎉 Выполнено! Серия: {days_word(item.current)} 🔥"


def already_done(name: str) -> str:
    return f"👍 <b>{escape(name)}</b> уже отмечена сегодня. Отличная работа!"


def not_found() -> str:
    return "🤔 Не нашёл такую привычку. Загляните в /list — номер указан рядом с названием."


def confirm_delete(item: HabitStats) -> str:
    return (
        f"🗑 <b>Удалить привычку?</b>\n{SEP}\n\n"
        f"{habit_card(item)}\n\n"
        f"Вместе с ней удалится вся история ({item.total} отметок). Это действие необратимо."
    )


def deleted(name: str) -> str:
    return f"🗑 Привычка «{escape(name)}» удалена."


def add_prompt() -> str:
    return (
        f"➕ <b>Новая привычка</b>\n{SEP}\n\n"
        f"Как её назвать? Напишите название (до {MAX_NAME_LENGTH} символов).\n"
        "Например: <i>Пить воду</i>, <i>Читать 20 минут</i>, <i>Зарядка</i>.\n\n"
        "Передумали? Отправьте /cancel."
    )


def add_usage() -> str:
    return (
        f"✏️ Название должно быть непустым и не длиннее {MAX_NAME_LENGTH} символов. "
        "Попробуйте ещё раз или отправьте /cancel."
    )


def limit_reached() -> str:
    return f"📦 Достигнут лимит — {MAX_HABITS_PER_USER} привычек. Удалите ненужную в /list."


def duplicate() -> str:
    return "🔁 Такая привычка уже есть. Выберите другое название."


def cancelled() -> str:
    return "👌 Отменено."


def bad_id(command: str) -> str:
    return (
        f"Укажите номер привычки: <code>/{command} 1</code>\n"
        "Номера видны в /list рядом с названиями (например, <code>#1</code>)."
    )


def unknown() -> str:
    return "🤔 Не понял. Выберите действие в меню ниже или отправьте /help."


# --- start / menu / settings / reminders ------------------------------------------------------


def welcome(first_name: str | None) -> str:
    name = escape(first_name) if first_name else "друг"
    return (
        f"👋 <b>Привет, {name}!</b>\n{SEP}\n\n"
        "Я помогу выработать полезные привычки и не потерять серию 🔥\n\n"
        "✅ Отмечайте привычки одним нажатием\n"
        "🔥 Следите за сериями и рекордами\n"
        "📊 Смотрите статистику недели\n"
        "🔔 Получайте ежедневные напоминания\n\n"
        "Начните с кнопки «➕ Добавить» или отправьте <code>/add Пить воду</code>.\n"
        "Меню всегда под рукой внизу 👇"
    )


def menu_text() -> str:
    return f"📱 <b>Меню</b>\n{SEP}\n\nВыберите действие кнопками ниже или на клавиатуре 👇"


def reminder_status(at: time | None) -> str:
    return f"ежедневно в <b>{at:%H:%M}</b>" if at else "выключено"


def settings_view(habits_count: int, at: time | None, tz_name: str) -> str:
    return (
        f"⚙️ <b>Настройки</b>\n{SEP}\n\n"
        f"📋 Привычек: <b>{habits_count}</b> из {MAX_HABITS_PER_USER}\n"
        f"🔔 Напоминание: {reminder_status(at)}\n"
        f"🌍 Часовой пояс: <b>{escape(tz_name)}</b>"
    )


def reminders_view(at: time | None) -> str:
    return (
        f"🔔 <b>Напоминания</b>\n{SEP}\n\n"
        f"Сейчас: {reminder_status(at)}\n\n"
        "Выберите время кнопкой или отправьте своё: <code>/remind 21:30</code>.\n"
        "В назначенный час я пришлю список невыполненных привычек."
    )


def reminder_usage() -> str:
    return (
        "⏰ Укажите время в формате ЧЧ:ММ, например <code>/remind 21:30</code>.\n"
        "Выключить: <code>/remind off</code>."
    )


def reminder_set(at: time) -> str:
    return f"⏰ Готово! Буду напоминать ежедневно в <b>{at:%H:%M}</b>."


def reminder_off(removed: bool) -> str:
    return "🔕 Напоминание выключено." if removed else "🔕 Напоминание и так не было включено."
