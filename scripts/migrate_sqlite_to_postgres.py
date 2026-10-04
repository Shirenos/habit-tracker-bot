"""Copy the bot's SQLite database into PostgreSQL (one-off, safe to run again).

Usage:
    python scripts/migrate_sqlite_to_postgres.py --sqlite data/habits.db \\
        --postgres postgresql://user:password@host:5432/habits

``--sqlite`` defaults to ``DATABASE_PATH`` and ``--postgres`` to ``DATABASE_URL`` (also read from
``.env``). The SQLite file is only read, never modified. Stop the bot while copying, otherwise
check-ins made during the copy are missed (run the script again afterwards to pick them up).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from habit_bot.pg import PostgresStorage, is_postgres_url
from habit_bot.sqlite_to_pg import copy_sqlite_to_postgres


async def _run(sqlite_path: Path, url: str) -> int:
    storage = PostgresStorage(url)
    await storage.connect()  # creates / migrates the PostgreSQL schema first
    try:
        report = await copy_sqlite_to_postgres(sqlite_path, storage)
    finally:
        await storage.close()
    print(
        f"Copied {report.habits} habits, {report.checkins} check-ins, "
        f"{report.reminders} reminders (existing rows are skipped)."
    )
    return 0


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--sqlite", default=os.getenv("DATABASE_PATH", "data/habits.db"))
    parser.add_argument("--postgres", default=os.getenv("DATABASE_URL", ""))
    args = parser.parse_args()
    if not args.postgres or not is_postgres_url(args.postgres):
        print("Error: pass --postgres postgresql://... or set DATABASE_URL.", file=sys.stderr)
        return 2
    try:
        return asyncio.run(_run(Path(args.sqlite), args.postgres))
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
