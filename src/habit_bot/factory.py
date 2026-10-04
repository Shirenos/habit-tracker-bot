"""Choose the storage backend from the settings."""

from __future__ import annotations

from habit_bot.config import Settings
from habit_bot.storage import Storage


def create_storage(settings: Settings) -> Storage:
    """PostgreSQL when ``DATABASE_URL`` is set, otherwise the SQLite file ``DATABASE_PATH``."""
    if settings.database_url:
        from habit_bot.pg import PostgresStorage  # lazy: asyncpg is an optional extra

        return PostgresStorage(settings.database_url)
    from habit_bot.db import Database

    return Database(settings.database_path)
