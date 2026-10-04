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
    assert [(h.name, done) for h, done in await service.list(1)] == [("Read", True)]


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
