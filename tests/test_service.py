from datetime import date, timedelta

from habit_bot.services.habits import MAX_HABITS_PER_USER, AddResult, DoneResult

TODAY = date(2026, 10, 3)


async def test_add_validation(service):
    assert (await service.add(1, "   "))[0] is AddResult.INVALID
    assert (await service.add(1, "x" * 65))[0] is AddResult.INVALID
    result, habit = await service.add(1, "  Drink   water ")
    assert result is AddResult.OK and habit.name == "Drink water"
    assert (await service.add(1, "Drink water"))[0] is AddResult.DUPLICATE


async def test_habit_limit(service):
    for i in range(MAX_HABITS_PER_USER):
        await service.add(1, f"h{i}")
    assert (await service.add(1, "one more"))[0] is AddResult.LIMIT


async def test_done_flow(service):
    _, habit = await service.add(1, "Read")
    assert (await service.done(1, habit.id))[0] is DoneResult.OK
    assert (await service.done(1, habit.id))[0] is DoneResult.ALREADY
    assert (await service.done(2, habit.id))[0] is DoneResult.NOT_FOUND
    assert (await service.done(1, 999))[0] is DoneResult.NOT_FOUND
    assert [(h.name, done) for h, done in await service.list_with_status(1)] == [("Read", True)]


async def test_stats(service):
    _, habit = await service.add(1, "Read")
    for offset in (0, 1, 2, 5):
        await service.done(1, habit.id, TODAY - timedelta(days=offset))

    (stats,) = await service.stats(1, today=TODAY)
    assert stats.current == 3
    assert stats.longest == 3
    assert stats.total == 4
    assert sum(done for _, done in stats.week) == 4


async def test_stats_done_today_and_timezone(service):
    _, habit = await service.add(1, "Read")
    assert service.timezone.key == "UTC"
    assert (await service.get(1, habit.id)).name == "Read"
    assert await service.get(2, habit.id) is None
    (before,) = await service.stats(1)
    assert before.done_today is False
    await service.done(1, habit.id)
    (after,) = await service.stats(1)
    assert after.done_today is True


async def test_names_are_case_insensitive_including_cyrillic(service):
    assert (await service.add(1, "Читать"))[0] is AddResult.OK
    assert (await service.add(1, "  читать "))[0] is AddResult.DUPLICATE
    assert (await service.add(1, "ЧИТАТЬ"))[0] is AddResult.DUPLICATE
    assert (await service.add(2, "ЧИТАТЬ"))[0] is AddResult.OK


async def count_selects(db) -> list[str]:
    """Start recording SELECT statements issued on the connection; returns the live list."""
    selects: list[str] = []

    def trace(sql: str) -> None:
        if sql.lstrip().upper().startswith("SELECT"):
            selects.append(sql)

    await db.conn.set_trace_callback(trace)
    return selects


async def test_list_with_status_uses_one_query(service, db):
    for name in ("A", "B", "C", "D"):
        await service.add(1, name)
    await service.done(1, 2)
    selects = await count_selects(db)
    result = await service.list_with_status(1)
    assert [(h.name, done) for h, done in result] == [
        ("A", False),
        ("B", True),
        ("C", False),
        ("D", False),
    ]
    assert len(selects) == 1


async def test_stats_uses_two_queries_and_matches_per_habit_computation(service, db):
    from habit_bot.services import streaks

    for name in ("A", "B", "C", "D", "E"):
        await service.add(1, name)
    for habit_id, offsets in {1: (0, 1, 2, 5), 2: (1, 2, 3), 4: (0,), 5: (0, 3, 4, 6, 9)}.items():
        for offset in offsets:
            await service.done(1, habit_id, TODAY - timedelta(days=offset))
    selects = await count_selects(db)
    stats = await service.stats(1, today=TODAY)
    assert len(selects) == 2  # habits + all check-ins, regardless of the habit count

    assert [s.habit.name for s in stats] == ["A", "B", "C", "D", "E"]
    for s in stats:
        days = await db.get_checkin_days(s.habit.id)
        assert s.current == streaks.current_streak(days, TODAY)
        assert s.longest == streaks.longest_streak(days)
        assert s.total == len(days)
        assert s.week == streaks.last_n_days(days, TODAY, 7)
    assert [s.total for s in stats] == [4, 3, 0, 1, 5]  # habit without check-ins is included
    assert await service.stats(2, today=TODAY) == []
