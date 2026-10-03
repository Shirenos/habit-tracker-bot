from zoneinfo import ZoneInfo

import pytest_asyncio

from habit_bot.db import Database
from habit_bot.services.habits import HabitService


@pytest_asyncio.fixture
async def db():
    database = Database(":memory:")
    await database.connect()
    yield database
    await database.close()


@pytest_asyncio.fixture
async def service(db):
    return HabitService(db, ZoneInfo("UTC"))
