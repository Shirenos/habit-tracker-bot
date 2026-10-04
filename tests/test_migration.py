"""SQLite -> PostgreSQL data copy (needs ``DATABASE_URL_TEST``; skipped otherwise)."""

import importlib.util
import sys
from datetime import date
from pathlib import Path

import pytest

from habit_bot.db import Database
from habit_bot.pg import PostgresStorage
from habit_bot.sqlite_to_pg import copy_sqlite_to_postgres

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "migrate_sqlite_to_postgres.py"


async def make_sqlite(path: Path) -> None:
    source = Database(path)
    await source.connect()
    try:
        read = await source.add_habit(1, "Читать")
        run = await source.add_habit(1, "Run")
        gone = await source.add_habit(2, "Gone")
        other = await source.add_habit(5_000_000_000, "Big id")
        await source.delete_habit(2, gone.id)  # leaves a gap in the ids
        for d in (date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3)):
            await source.add_checkin(read.id, d)
        await source.add_checkin(run.id, date(2026, 10, 3))
        await source.add_checkin(other.id, date(2026, 10, 3))
        await source.set_reminder(1, 100, "21:30")
        await source.set_reminder(5_000_000_000, 5_000_000_000, "08:00")
    finally:
        await source.close()


async def test_copy_preserves_data_and_is_idempotent(tmp_path, pg_storage):
    path = tmp_path / "habits.db"
    await make_sqlite(path)

    first = await copy_sqlite_to_postgres(path, pg_storage)
    assert (first.habits, first.checkins, first.reminders) == (3, 5, 2)

    habits = await pg_storage.list_habits(1)
    assert [h.name for h in habits] == ["Читать", "Run"]
    assert await pg_storage.get_checkin_days(habits[0].id) == {
        date(2026, 10, 1),
        date(2026, 10, 2),
        date(2026, 10, 3),
    }
    assert (await pg_storage.get_reminder(1)).time == "21:30"
    assert (await pg_storage.get_reminder(5_000_000_000)).chat_id == 5_000_000_000
    assert await pg_storage.add_habit(1, "читать") is None  # name_key was copied

    second = await copy_sqlite_to_postgres(path, pg_storage)  # run it again
    assert (second.habits, second.checkins, second.reminders) == (0, 0, 0)
    assert len(await pg_storage.list_habits(1)) == 2


async def test_new_habits_get_ids_after_the_copied_ones(tmp_path, pg_storage):
    path = tmp_path / "habits.db"
    await make_sqlite(path)
    await copy_sqlite_to_postgres(path, pg_storage)
    highest = max(h.id for h in await pg_storage.list_habits(1))
    created = await pg_storage.add_habit(1, "Brand new")
    assert created.id > highest
    # ... also above the id of a habit that only exists for another user
    assert created.id > (await pg_storage.list_habits(5_000_000_000))[0].id


async def test_copy_of_empty_database(tmp_path, pg_storage):
    path = tmp_path / "empty.db"
    empty = Database(path)
    await empty.connect()
    await empty.close()
    report = await copy_sqlite_to_postgres(path, pg_storage)
    assert (report.habits, report.checkins, report.reminders) == (0, 0, 0)
    assert (await pg_storage.add_habit(1, "First")).id == 1


async def test_copy_refuses_missing_and_outdated_sqlite(tmp_path, pg_storage):
    with pytest.raises(FileNotFoundError):
        await copy_sqlite_to_postgres(tmp_path / "nope.db", pg_storage)
    import sqlite3

    old = tmp_path / "old.db"
    con = sqlite3.connect(old)
    con.execute("CREATE TABLE habits (id INTEGER)")
    con.commit()
    con.close()
    with pytest.raises(RuntimeError, match="Start the bot once"):
        await copy_sqlite_to_postgres(old, pg_storage)


def load_script():
    spec = importlib.util.spec_from_file_location("migrate_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["migrate_script"] = module
    spec.loader.exec_module(module)
    return module


def test_script_requires_a_postgres_url(monkeypatch, capsys, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.chdir(tmp_path)  # no .env here
    monkeypatch.setattr(sys, "argv", ["migrate", "--sqlite", "x.db"])
    assert load_script().main() == 2
    assert "DATABASE_URL" in capsys.readouterr().err


async def test_script_end_to_end(tmp_path, pg_storage, capsys, monkeypatch):
    path = tmp_path / "habits.db"
    await make_sqlite(path)
    script = load_script()
    # Keep the test inside its throw-away schema instead of the server's default one.
    monkeypatch.setattr(
        script, "PostgresStorage", lambda url: PostgresStorage(url, schema=pg_storage._schema)
    )
    assert await script._run(path, pg_storage._dsn) == 0
    assert "Copied 3 habits, 5 check-ins, 2 reminders" in capsys.readouterr().out
