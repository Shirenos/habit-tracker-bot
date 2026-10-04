"""PostgreSQL-specific behaviour (the shared contract runs through the ``db`` fixture).

These tests need a server: set ``DATABASE_URL_TEST`` (CI provides one); otherwise they are skipped.
"""

import pytest

from habit_bot.config import ConfigError, Settings, load_settings
from habit_bot.db import Database
from habit_bot.factory import create_storage
from habit_bot.pg import SCHEMA_VERSION, PostgresStorage, is_postgres_url


async def stored_version(storage: PostgresStorage) -> int:
    return await storage.pool.fetchval("SELECT version FROM schema_version")


async def test_fresh_schema_has_current_version_and_one_version_row(pg_storage):
    assert await stored_version(pg_storage) == SCHEMA_VERSION
    assert await pg_storage.pool.fetchval("SELECT COUNT(*) FROM schema_version") == 1


async def test_reconnect_is_idempotent_and_keeps_data(pg_storage):
    await pg_storage.add_habit(1, "Read")
    again = PostgresStorage(pg_storage._dsn, schema=pg_storage._schema)
    await again.connect()  # runs the migration check again
    try:
        assert [h.name for h in await again.list_habits(1)] == ["Read"]
        assert await stored_version(again) == SCHEMA_VERSION
        assert await again.pool.fetchval("SELECT COUNT(*) FROM schema_version") == 1
    finally:
        await again.close()


async def test_newer_schema_version_is_refused(pg_storage):
    await pg_storage.pool.execute("UPDATE schema_version SET version = $1", SCHEMA_VERSION + 1)
    other = PostgresStorage(pg_storage._dsn, schema=pg_storage._schema)
    with pytest.raises(RuntimeError, match="newer"):
        await other.connect()
    assert other._pool is None  # the pool was closed again


async def test_name_key_is_stored_casefolded(pg_storage):
    await pg_storage.add_habit(1, "Straße")
    key = await pg_storage.pool.fetchval("SELECT name_key FROM habits")
    assert key == "strasse"
    assert await pg_storage.add_habit(1, "STRASSE") is None


async def test_created_at_is_timestamptz_in_utc(pg_storage):
    await pg_storage.add_habit(1, "Read")
    row = await pg_storage.pool.fetchrow(
        "SELECT created_at, pg_typeof(created_at)::text AS t, "
        "extract(timezone FROM created_at) AS tz FROM habits"
    )
    assert row["t"] == "timestamp with time zone"
    assert row["created_at"].utcoffset().total_seconds() == 0


async def test_deleting_a_habit_cascades_to_checkins(pg_storage):
    from datetime import date

    habit = await pg_storage.add_habit(1, "Read")
    await pg_storage.add_checkin(habit.id, date(2026, 10, 3))
    await pg_storage.delete_habit(1, habit.id)
    assert await pg_storage.pool.fetchval("SELECT COUNT(*) FROM checkins") == 0


async def test_db_size_comes_from_pg_database_size(pg_storage):
    from datetime import date

    stats = await pg_storage.get_admin_stats(date(2026, 10, 4))
    real = await pg_storage.pool.fetchval("SELECT pg_database_size(current_database())")
    assert stats.db_size_bytes > 0 and abs(stats.db_size_bytes - real) < 5_000_000


async def test_using_unconnected_storage_raises():
    with pytest.raises(RuntimeError, match="not connected"):
        await PostgresStorage("postgresql://localhost/none").list_habits(1)


async def test_connection_failure_does_not_leak_the_password():
    storage = PostgresStorage("postgresql://u:s3cr3t-pw@127.0.0.1:1/none")
    with pytest.raises(OSError) as info:
        await storage.connect()
    assert "s3cr3t-pw" not in str(info.value)


def test_is_postgres_url():
    assert is_postgres_url("postgresql://u:p@h/db")
    assert is_postgres_url("postgres://u:p@h/db")
    assert not is_postgres_url("sqlite:///x.db")
    assert not is_postgres_url("data/habits.db")


def test_config_database_url(monkeypatch, tmp_path):
    monkeypatch.setenv("BOT_TOKEN", "dummy-test-token")
    missing = tmp_path / "missing.env"
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert load_settings(missing).database_url is None  # SQLite stays the default
    monkeypatch.setenv("DATABASE_URL", "  ")
    assert load_settings(missing).database_url is None
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db:5432/habits")
    assert load_settings(missing).database_url == "postgresql://u:p@db:5432/habits"
    monkeypatch.setenv("DATABASE_URL", "mysql://u:topsecret@db/habits")
    with pytest.raises(ConfigError) as info:
        load_settings(missing)
    assert "topsecret" not in str(info.value)


def test_factory_selects_backend(tmp_path):
    from zoneinfo import ZoneInfo

    base = {"bot_token": "x", "database_path": tmp_path / "a.db", "timezone": ZoneInfo("UTC")}
    assert isinstance(create_storage(Settings(**base)), Database)
    chosen = create_storage(Settings(**base, database_url="postgresql://u:p@h/db"))
    assert isinstance(chosen, PostgresStorage)
