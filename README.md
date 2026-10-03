# 🌱 Habit Tracker Bot

A Telegram bot that helps you build habits, keep streaks alive and never forget a daily check-in.
Built with **aiogram 3**, **SQLite (aiosqlite)** and a tiny dependency-free **asyncio scheduler**.

[![CI](https://github.com/Shirenos/habit-tracker-bot/actions/workflows/ci.yml/badge.svg)](https://github.com/Shirenos/habit-tracker-bot/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white)
![aiogram](https://img.shields.io/badge/aiogram-3.x-2CA5E0?logo=telegram&logoColor=white)
![SQLite](https://img.shields.io/badge/storage-SQLite-003B57?logo=sqlite&logoColor=white)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-261230?logo=ruff&logoColor=white)](https://docs.astral.sh/ruff/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

> Replace `Shirenos` in the CI badge URL with your GitHub username after publishing.

## ✨ Features

- **Track habits** — add, list and delete personal habits (per-user, isolated).
- **Daily check-ins** — mark a habit done with one command; double check-ins are idempotent.
- **Streaks & stats** — current streak, best streak, total completions and a 🟩⬜ view of the last 7 days.
- **Daily reminder** — pick a time with `/remind 21:30`; reminders survive restarts.
- **Timezone aware** — "today" and reminders follow a configurable IANA timezone.
- **Safe output** — user input is HTML-escaped; length and count limits per user.
- **Production ready** — Dockerfile, docker-compose with a persistent volume, CI with ruff + pytest.

## 💬 Commands

| Command | Description |
| --- | --- |
| `/start` | Welcome message |
| `/help` | List of commands |
| `/add <habit>` | Create a habit, e.g. `/add Drink water` |
| `/list` | Show habits and whether they're done today |
| `/done <id>` | Mark a habit as done today |
| `/stats` | Streaks and the last 7 days for each habit |
| `/delete <id>` | Delete a habit and its history |
| `/remind HH:MM` | Daily reminder at the given time (24h). `/remind off` disables it |

## 🚀 Quickstart

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the token.
2. Configure the environment:

   ```bash
   cp .env.example .env
   # edit .env and set BOT_TOKEN (and TIMEZONE, e.g. Europe/Moscow)
   ```

### Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -e .
python -m habit_bot          # or: habit-bot
```

### Run with Docker

```bash
docker compose up -d --build
docker compose logs -f
```

The SQLite database lives in the `bot-data` volume, so data survives container rebuilds.

### Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `BOT_TOKEN` | — (required) | Telegram bot token from @BotFather |
| `DATABASE_PATH` | `data/habits.db` | SQLite file location |
| `TIMEZONE` | `UTC` | IANA timezone for "today" and reminders |
| `LOG_LEVEL` | `INFO` | Python logging level |

> 🔐 Never commit `.env` — it is already in `.gitignore`.

## 🧪 Development

```bash
pip install -r requirements-dev.txt -e .
ruff check . && ruff format --check .
pytest
```

Tests cover the streak maths, the database layer (including cascade deletes and persistence),
the service layer, reminder parsing/scheduling, configuration and the command handlers.
CI runs the same checks on Python 3.11, 3.12 and 3.13.

## 🗂 Project structure

```
habit-tracker-bot/
├── src/habit_bot/
│   ├── config.py          # Settings from env / .env
│   ├── db.py              # aiosqlite repository + schema
│   ├── main.py            # Wiring: bot, dispatcher, scheduler
│   ├── handlers/          # aiogram routers (basic, habits, reminders)
│   └── services/
│       ├── streaks.py     # Pure streak / history logic
│       ├── habits.py      # Business logic on top of the DB
│       └── reminders.py   # asyncio-based daily reminder scheduler
├── tests/                 # pytest + pytest-asyncio
├── .github/workflows/     # CI: ruff + pytest
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml
```

### Design notes

- **Layers**: handlers only parse Telegram input and format replies; services hold the logic;
  `db.py` is the only module that speaks SQL. Streak maths is pure and trivially testable.
- **Streak rule**: a streak is the run of consecutive done days ending today — or yesterday, so
  your streak doesn't read `0` before you've had the chance to check in.
- **Scheduler**: one asyncio task per user sleeping until the next `HH:MM` in the configured
  timezone; tasks are restored from SQLite on startup.

## 🗺 Roadmap

- [ ] Inline keyboard buttons for `/done` straight from the reminder
- [ ] Per-user timezones (`/timezone`)
- [ ] Multiple reminders and per-habit reminders
- [ ] Weekly goals and custom schedules (e.g. Mon/Wed/Fri)
- [ ] Charts / monthly heatmap export
- [ ] Webhook mode and a `/export` command (CSV)
- [ ] Localisation (i18n)

## 🤝 Contributing

Issues and PRs are welcome. Please run `ruff` and `pytest` before submitting.

## 📄 License

[MIT](LICENSE) © 2026 Shiren
