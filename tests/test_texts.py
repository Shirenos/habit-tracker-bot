from datetime import date, timedelta

import pytest

from habit_bot import keyboards as kb
from habit_bot import texts
from habit_bot.db import Habit
from habit_bot.services import streaks
from habit_bot.services.habits import MAX_HABITS_PER_USER, HabitStats

TODAY = date(2026, 10, 4)  # Sunday


def make_stats(habit_id: int, name: str, offsets: tuple[int, ...]) -> HabitStats:
    days = {TODAY - timedelta(days=o) for o in offsets}
    return HabitStats(
        habit=Habit(habit_id, 1, name),
        current=streaks.current_streak(days, TODAY),
        longest=streaks.longest_streak(days),
        total=len(days),
        week=streaks.last_n_days(days, TODAY, 7),
    )


@pytest.mark.parametrize(
    ("n", "word"),
    [(1, "день"), (2, "дня"), (4, "дня"), (5, "дней"), (11, "дней"), (12, "дней"),
     (21, "день"), (22, "дня"), (100, "дней"), (111, "дней"), (0, "дней")],
)  # fmt: skip
def test_plural(n, word):
    assert texts.plural(n, "день", "дня", "дней") == word


def test_bar():
    assert texts.bar(0, 5) == "▱▱▱▱▱"
    assert texts.bar(3, 5) == "▰▰▰▱▱"
    assert texts.bar(5, 5) == "▰▰▰▰▰"
    assert texts.bar(1, 100) == "▰▱▱▱▱"  # never looks empty when something is done
    assert texts.bar(99, 100) == "▰▰▰▰▱"  # ... or full when something is missing
    assert texts.bar(0, 0) == "▱▱▱▱▱" and len(texts.bar(3, 7, 7)) == 7


def test_date_phrase_and_range():
    assert texts.date_phrase(TODAY) == "Воскресенье, 4 октября"
    assert texts.short_range(date(2026, 10, 1), date(2026, 10, 7)) == "1 – 7 октября"
    assert texts.short_range(date(2026, 9, 28), date(2026, 10, 4)) == "28 сентября – 4 октября"


def test_habit_card_escapes_and_shows_streak():
    card = texts.habit_card(make_stats(3, "<script>&", (0, 1, 2)))
    assert "&lt;script&gt;&amp;" in card and "<script>" not in card
    assert "✅" in card and "🔥 3 дня" in card and "▰▰▰▱▱▱▱ 3/7" in card and "#3" in card
    assert "🌱 серия впереди" in texts.habit_card(make_stats(1, "x", ()))


def test_week_chart_counts_per_day():
    stats = [make_stats(1, "a", (0, 1)), make_stats(2, "b", (0,))]
    rows = texts.week_chart(stats, TODAY).splitlines()
    assert len(rows) == 7
    assert rows[-1].startswith("Вс  4 ▰▰▰▰▰ 2/2") and rows[-1].endswith("← сегодня")
    assert rows[-2].startswith("Сб  3 ▰▰▱▱▱ 1/2")
    assert rows[0].startswith("Пн 28 ▱▱▱▱▱ 0/2")


def test_today_view_progress_and_phrase():
    open_ = texts.today_view([make_stats(1, "a", ()), make_stats(2, "b", (0,))], TODAY)
    assert "<b>1/2</b> · 50%" in open_ and "Воскресенье, 4 октября" in open_
    done = texts.today_view([make_stats(1, "a", (0,))], TODAY)
    assert "<b>1/1</b> · 100%" in done and "💬" in done
    assert "Время для привычек" in texts.today_view([make_stats(1, "a", ())], TODAY, reminder=True)


def test_done_reply_milestone_and_record():
    text = texts.done_reply(make_stats(1, "Бег", (0, 1, 2)), TODAY)
    assert "🔥 3 дня" in text and "новый рекорд" in text and "До 7 дней" in text and "3/7" in text
    assert "новый рекорд" not in texts.done_reply(make_stats(1, "Бег", (0,)), TODAY)


def test_stats_view_sections():
    text = texts.stats_view([make_stats(1, "Бег", (0, 1)), make_stats(2, "Йога", ())], TODAY)
    for part in ("Статистика", "<pre>", "28 сентября – 4 октября", "Выполнено <b>2 из 14</b>",
                 "Лучшая серия: <b>Бег</b>", "По привычкам", "🟩", "🏆 рекорд 2"):  # fmt: skip
        assert part in text
    assert "Пока считать нечего" in texts.stats_view([], TODAY)


def test_stats_phrase_tiers():
    assert "потрясающей" in texts.stats_phrase(9, 10, TODAY)
    assert "Хороший ритм" in texts.stats_phrase(5, 10, TODAY)
    assert "Начало" in texts.stats_phrase(1, 10, TODAY)
    assert texts.stats_phrase(0, 10, TODAY) in texts.PHRASES_NONE


def test_welcome_escapes_name():
    assert "&lt;i&gt;" in texts.welcome("<i>") and "друг" in texts.welcome(None)


def test_messages_fit_telegram_limit_with_max_habits():
    long_name = "я" * 60 + "<&>"  # escaping makes names longer
    stats = [make_stats(i, long_name, (0, 1, 2, 4)) for i in range(1, MAX_HABITS_PER_USER + 1)]
    for text in (
        texts.today_view(stats, TODAY),
        texts.list_view(stats),
        texts.stats_view(stats, TODAY),
    ):
        assert len(text) < 4096


def test_callback_data_fits_and_keyboards_are_consistent():
    stats = [make_stats(10**9 + i, "я" * 64, ()) for i in range(MAX_HABITS_PER_USER)]
    markups = [
        kb.today_kb(stats),
        kb.list_kb(stats),
        kb.stats_kb(),
        kb.empty_kb(),
        kb.confirm_delete_kb(10**9),
        kb.added_kb(10**9),
        kb.after_done_kb(),
        kb.cancel_kb(),
        kb.reminders_kb("08:00"),
        kb.settings_kb(),
        kb.help_kb(),
    ]
    for markup in markups:
        for row in markup.inline_keyboard:
            for button in row:
                assert len(button.callback_data.encode()) <= 64
                assert len(button.text) <= 40
    assert len(kb.list_kb(stats).inline_keyboard) <= 100
