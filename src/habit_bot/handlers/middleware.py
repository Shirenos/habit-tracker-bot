from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message

from habit_bot.keyboards import MENU_BUTTONS


class ResetStateMiddleware(BaseMiddleware):
    """Leave the "type a habit name" dialog when the user taps a menu button or sends a command.

    ``/cancel`` is left to its own handler so it can tell whether anything was running.
    """

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,  # type: ignore[override]
        data: dict[str, Any],
    ) -> Any:
        text = event.text or ""
        state = data.get("state")
        if state is not None and (
            (text.startswith("/") and not text.startswith("/cancel")) or text in MENU_BUTTONS
        ):
            await state.clear()
        return await handler(event, data)
