"""Pure streak / history calculations (no I/O, easy to test)."""

from __future__ import annotations

from collections.abc import Collection
from datetime import date, timedelta


def current_streak(days: Collection[date], today: date) -> int:
    """Length of the run of consecutive days ending today.

    If today is not done yet, the streak is still alive as long as yesterday was
    done, so users don't see their streak drop to 0 in the morning.
    """
    cursor = today if today in days else today - timedelta(days=1)
    streak = 0
    while cursor in days:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def longest_streak(days: Collection[date]) -> int:
    """Longest run of consecutive days ever recorded."""
    best = run = 0
    prev: date | None = None
    for d in sorted(set(days)):
        run = run + 1 if prev is not None and d - prev == timedelta(days=1) else 1
        best = max(best, run)
        prev = d
    return best


def last_n_days(days: Collection[date], today: date, n: int = 7) -> list[tuple[date, bool]]:
    """``n`` (day, done) pairs ending today, oldest first."""
    return [(d, d in days) for d in (today - timedelta(days=i) for i in range(n - 1, -1, -1))]
