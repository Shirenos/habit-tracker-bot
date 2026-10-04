from datetime import date

import pytest

from habit_bot.db import Database


async def test_add_and_list_habits(db):
    h = await db.add_habit(1, "Read")
    assert h is not None and h.id > 0
    await db.add_habit(1, "Run")
    await db.add_habit(2, "Other user")
    assert [x.name for x in await db.list_habits(1)] == ["Read", "Run"]


async def test_duplicate_name_per_user_rejected(db):
    assert await db.add_habit(1, "Read") is not None
    assert await db.add_habit(1, "Read") is None
    assert await db.add_habit(2, "Read") is not None


async def test_get_and_delete_are_scoped_to_owner(db):
    h = await db.add_habit(1, "Read")
    assert await db.get_habit(2, h.id) is None
    assert await db.delete_habit(2, h.id) is False
    assert await db.delete_habit(1, h.id) is True
    assert await db.list_habits(1) == []


async def test_checkins_idempotent(db):
    h = await db.add_habit(1, "Read")
    day = date(2026, 10, 3)
    assert await db.add_checkin(h.id, day) is True
    assert await db.add_checkin(h.id, day) is False
    assert await db.get_checkin_days(h.id) == {day}


async def test_delete_cascades_checkins(db):
    h = await db.add_habit(1, "Read")
    await db.add_checkin(h.id, date(2026, 10, 3))
    await db.delete_habit(1, h.id)
    async with db.conn.execute("SELECT COUNT(*) FROM checkins") as cur:
        assert (await cur.fetchone())[0] == 0


async def test_reminder_upsert_and_remove(db):
    await db.set_reminder(1, 100, "09:00")
    await db.set_reminder(1, 100, "21:30")
    reminders = await db.list_reminders()
    assert len(reminders) == 1 and reminders[0].time == "21:30"
    assert await db.remove_reminder(1) is True
    assert await db.remove_reminder(1) is False


async def test_data_persists_on_disk(tmp_path):
    path = tmp_path / "nested" / "test.db"
    first = Database(path)
    await first.connect()
    await first.add_habit(1, "Read")
    await first.close()

    second = Database(path)
    await second.connect()
    assert [h.name for h in await second.list_habits(1)] == ["Read"]
    await second.close()


async def test_using_closed_db_raises():
    with pytest.raises(RuntimeError):
        await Database(":memory:").list_habits(1)


async def test_get_reminder(db):
    assert await db.get_reminder(1) is None
    await db.set_reminder(1, 100, "08:00")
    reminder = await db.get_reminder(1)
    assert (reminder.chat_id, reminder.time) == (100, "08:00")
    assert await db.get_reminder(2) is None
