from datetime import date, timedelta

from habit_bot.services.streaks import current_streak, last_n_days, longest_streak

TODAY = date(2026, 10, 3)


def d(offset: int) -> date:
    return TODAY - timedelta(days=offset)


def test_current_streak_empty():
    assert current_streak(set(), TODAY) == 0


def test_current_streak_including_today():
    assert current_streak({d(0), d(1), d(2)}, TODAY) == 3


def test_current_streak_alive_when_today_not_done_yet():
    assert current_streak({d(1), d(2)}, TODAY) == 2


def test_current_streak_broken_by_gap():
    assert current_streak({d(2), d(3), d(4)}, TODAY) == 0


def test_current_streak_stops_at_first_gap():
    assert current_streak({d(0), d(1), d(3), d(4)}, TODAY) == 2


def test_longest_streak():
    assert longest_streak(set()) == 0
    assert longest_streak({d(0)}) == 1
    assert longest_streak({d(0), d(1), d(5), d(6), d(7), d(8), d(20)}) == 4


def test_longest_streak_across_month_boundary():
    days = {date(2026, 1, 30), date(2026, 1, 31), date(2026, 2, 1)}
    assert longest_streak(days) == 3


def test_last_n_days_shape_and_order():
    week = last_n_days({d(0), d(2)}, TODAY, 7)
    assert len(week) == 7
    assert week[0][0] == d(6) and week[-1][0] == TODAY
    assert [done for _, done in week] == [False, False, False, False, True, False, True]
