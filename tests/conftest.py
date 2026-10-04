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


# --- end-to-end harness: real Dispatcher + routers, fake Telegram HTTP session -----------------

import itertools  # noqa: E402
from collections.abc import AsyncIterator  # noqa: E402
from datetime import UTC, datetime  # noqa: E402
from typing import Any  # noqa: E402

from aiogram import Bot, Dispatcher  # noqa: E402
from aiogram.client.session.base import BaseSession  # noqa: E402
from aiogram.exceptions import TelegramBadRequest  # noqa: E402
from aiogram.methods import EditMessageText, SendMessage  # noqa: E402
from aiogram.types import CallbackQuery, Chat, Message, Update, User  # noqa: E402

from habit_bot.handlers import basic, build_router, fallback, habits, reminders  # noqa: E402
from habit_bot.services.reminders import ReminderScheduler  # noqa: E402


class FakeSession(BaseSession):
    """Records every Bot API call instead of doing HTTP."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, Any]] = []
        self._ids = itertools.count(1000)
        self._last_edit: dict[int, tuple[str, str]] = {}

    async def close(self) -> None: ...

    async def stream_content(self, *args: Any, **kwargs: Any) -> AsyncIterator[bytes]:
        yield b""

    async def make_request(self, bot: Bot, method: Any, timeout: int | None = None) -> Any:
        name = type(method).__name__
        self.calls.append((name, method))
        chat = Chat(id=1, type="private")
        if isinstance(method, SendMessage):
            return Message(
                message_id=next(self._ids), date=datetime.now(UTC), chat=chat, text=method.text
            )
        if isinstance(method, EditMessageText):
            signature = (method.text, repr(method.reply_markup))
            if self._last_edit.get(method.message_id) == signature:
                raise TelegramBadRequest(method, "Bad Request: message is not modified")
            self._last_edit[method.message_id] = signature
            return Message(
                message_id=method.message_id or 0,
                date=datetime.now(UTC),
                chat=chat,
                text=method.text,
            )
        return True


class Chat1:
    """One user (id 1) talking to the bot; helpers return what the bot sent in response."""

    def __init__(self, dp: Dispatcher, bot: Bot, session: FakeSession, user_id: int = 1) -> None:
        self.dp, self.bot, self.session = dp, bot, session
        self.user = User(id=user_id, is_bot=False, first_name="Аня")
        self.chat = Chat(id=user_id, type="private")
        self._update_ids = itertools.count(1)
        self._msg_ids = itertools.count(1)

    def _message(self, text: str | None, message_id: int | None = None) -> Message:
        return Message(
            message_id=message_id or next(self._msg_ids),
            date=datetime.now(UTC),
            chat=self.chat,
            from_user=self.user,
            text=text,
        )

    async def say(self, text: str) -> list[Any]:
        """Send a message; returns the Bot API calls it triggered."""
        start = len(self.session.calls)
        update = Update(update_id=next(self._update_ids), message=self._message(text))
        await self.dp.feed_update(self.bot, update)
        return [m for _, m in self.session.calls[start:]]

    async def press(self, data: str, message_id: int = 500) -> list[Any]:
        start = len(self.session.calls)
        query = CallbackQuery(
            id=str(next(self._update_ids)),
            from_user=self.user,
            chat_instance="ci",
            data=data,
            message=self._message("old", message_id),
        )
        await self.dp.feed_update(
            self.bot, Update(update_id=next(self._update_ids), callback_query=query)
        )
        return [m for _, m in self.session.calls[start:]]


def last(calls: list[Any], cls: type) -> Any:
    return next(c for c in reversed(calls) if isinstance(c, cls))


@pytest_asyncio.fixture
async def scheduler(db):
    async def send(*_args: Any, **_kwargs: Any) -> None: ...

    sched = ReminderScheduler(db, send, ZoneInfo("UTC"))
    yield sched
    await sched.stop()


@pytest_asyncio.fixture
async def chat(service, scheduler):
    session = FakeSession()
    bot = Bot("123456:TEST-TOKEN", session=session)
    # Feature routers are module-level singletons; detach them so every test can build a fresh tree.
    for module in (basic, fallback, habits, reminders):
        module.router._parent_router = None
    dp = Dispatcher(habits=service, scheduler=scheduler)
    dp.include_router(build_router())
    return Chat1(dp, bot, session)
