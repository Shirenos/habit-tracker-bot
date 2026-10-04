"""Application configuration loaded from environment variables / .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv


class ConfigError(RuntimeError):
    """Raised when the configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    database_path: Path
    timezone: ZoneInfo
    log_level: str = "INFO"
    admin_ids: frozenset[int] = frozenset()
    database_url: str | None = None  # PostgreSQL DSN; when set it takes precedence over SQLite


def parse_admin_ids(raw: str) -> frozenset[int]:
    """Parse ``ADMIN_IDS``: comma-separated numeric user IDs (blank entries are ignored)."""
    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError:
            raise ConfigError(
                f"ADMIN_IDS must be comma-separated numeric user IDs, got {part!r}"
            ) from None
    return frozenset(ids)


def load_settings(env_file: str | os.PathLike[str] | None = None) -> Settings:
    """Build :class:`Settings` from the environment (and an optional .env file)."""
    load_dotenv(env_file)

    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise ConfigError("BOT_TOKEN is not set. Copy .env.example to .env and fill it in.")

    tz_name = os.getenv("TIMEZONE", "UTC").strip() or "UTC"
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError as exc:
        raise ConfigError(f"Unknown TIMEZONE: {tz_name!r}") from exc

    database_url = os.getenv("DATABASE_URL", "").strip() or None
    if database_url is not None and urlsplit(database_url).scheme not in {"postgresql", "postgres"}:
        # Do not echo the value: it normally contains a password.
        raise ConfigError("DATABASE_URL must start with postgresql:// (or postgres://).")

    return Settings(
        bot_token=token,
        database_path=Path(os.getenv("DATABASE_PATH", "data/habits.db")),
        timezone=tz,
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        admin_ids=parse_admin_ids(os.getenv("ADMIN_IDS", "")),
        database_url=database_url,
    )
